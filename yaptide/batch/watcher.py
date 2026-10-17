"""Follows one simulation task on the cluster: its progress goes into object storage, a cancel stops it.

Runs next to the simulator on the compute node, with the standard library only. The task's state goes into one
small object of its own, at most every few seconds and at once when the state changes; the backend's engine reads
these objects. The result files SHIELD-HIT12A saves along the way go into storage too, for the engine to merge into
partial results. A cancel is an object the backend puts into storage: the watcher checks for it and kills the
simulator. The signed links come in storage_links.json, written at submit; when they expire (after a week),
the watcher asks the backend for new ones.
"""

import argparse
import json
import logging
import os
import re
import signal
import ssl
import tarfile
import time
import uuid
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple
from urllib import error, request

RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
# logged when a save every NSAVE primaries has written all result files
SAVED_MATCH = r"\bSaved all \d+ estimator\(s\)"
# FLUKA's output: progress lines (six numbers) follow NEXT SEEDS, the run ends with an "End of FLUKA" banner
FLUKA_IN_PROGRESS = " NEXT SEEDS:"
FLUKA_COLLECTED = " All cases handled by Feeder"
FLUKA_END = re.compile(r"^ \* ======(?:( )*?)End of FLUKA [\w\-.]* run (?:( )*?) ====== \*")

# the TLS certificate chain of the backend is not always complete for the cluster's OpenSSL, as in the other scripts
CONTEXT = ssl.create_default_context()
CONTEXT.check_hostname = False
CONTEXT.verify_mode = ssl.CERT_NONE  # skipcq: PTC-W6001 # see above
# how long the simulator gets to stop before it is killed
STOP_SECONDS = 10
# new links are asked for a day before they expire, and not more often than this
RENEW_BEFORE_SECONDS = 24 * 3600
RENEW_INTERVAL_SECONDS = 600
# the final state is retried for about two minutes, longer than a restart of the storage
FINAL_ATTEMPTS = 6
FINAL_RETRY_SECONDS = 20
# a save goes into storage at most this often, and once it covers this much more of the task's primaries (half the
# step of saving the backend sets, which a save may miss by a few primaries): at most twenty per task
SAVE_SECONDS = 60
SAVE_GROWTH = 0.05


def log_generator(
    thefile: TextIOWrapper,
    event=None,
    max_idle_seconds: float = 3600,
    polling_interval_seconds: float = 1,
) -> Iterator[str]:
    """`tail -f` of a log file: yields the lines appended to it, waits for new ones (used by the direct engine too)

    Raises TimeoutError when nothing new comes for max_idle_seconds.
    """
    if thefile is None:
        raise ValueError("File object cannot be None.")
    idle_seconds = 0
    while True:
        if event and event.is_set():
            break
        line = thefile.readline()
        if not line:
            if event:
                if event.wait(polling_interval_seconds):
                    break
            else:
                time.sleep(polling_interval_seconds)
            idle_seconds += polling_interval_seconds
            if idle_seconds >= max_idle_seconds:
                raise TimeoutError("No new log data received before timeout.")
            continue
        idle_seconds = 0
        yield line


def now() -> str:
    """Current time as the backend stores task times"""
    return datetime.utcnow().isoformat(sep=" ", timespec="microseconds")


def shieldhit_update(line: str) -> Optional[dict]:
    """What a line of SHIELD-HIT12A's log says about the task, if anything"""
    if re.search(RUN_MATCH, line):
        parts = line.split()
        return {
            "simulated_primaries": int(parts[3]),
            "estimated_time": int(parts[9]) + int(parts[7]) * 60 + int(parts[5]) * 3600,
        }
    if re.search(REQUESTED_MATCH, line):
        return {
            "simulated_primaries": 0,
            "requested_primaries": int(line.split(": ")[1]),
            "start_time": now(),
            "task_state": "RUNNING",
        }
    if re.search(COMPLETE_MATCH, line):
        return {"end_time": now(), "task_state": "COMPLETED"}
    return None


class FlukaParser:
    """What lines of FLUKA's output say about the task; progress lines count only after NEXT SEEDS"""

    def __init__(self):
        """Before the run"""
        self.in_progress = False
        self.requested = 0

    def __call__(self, line: str) -> Optional[dict]:
        """The update a line carries, if any"""
        if FLUKA_END.match(line):
            return {"end_time": now(), "task_state": "COMPLETED", "simulated_primaries": self.requested}
        if line.startswith(FLUKA_IN_PROGRESS):
            self.in_progress = True
            return None
        if line.startswith(FLUKA_COLLECTED):
            self.in_progress = False
            return None
        parts = line.split()
        if not self.in_progress or len(parts) != 6:
            return None
        try:
            done, remaining = int(float(parts[0])), int(float(parts[1]))
        except ValueError:
            return None
        if not self.requested:
            self.requested = done + remaining
            return {
                "simulated_primaries": done,
                "requested_primaries": self.requested,
                "start_time": now(),
                "task_state": "RUNNING",
            }
        return {"simulated_primaries": done}


def multipart(fields: dict, body: bytes) -> Tuple[bytes, str]:
    """A multipart/form-data body (an S3 POST upload: the policy fields, then the file) and its content type"""
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="report.json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode()
        + body
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Reporter:
    """Puts the task's state into storage and looks there for a cancel"""

    def __init__(self, links_path: Path, task_id: int, interval_seconds: float, backend: dict):
        """interval_seconds: how often progress is reported and a cancel looked for; backend: sim_id, update_key
        (by default the one in the links file) and backend_url, for new links before the old ones expire
        """
        self.links_path = links_path
        self.links = json.loads(links_path.read_text())
        self.task_id = task_id
        self.interval_seconds = interval_seconds
        self.backend = dict(backend, update_key=backend.get("update_key") or self.links.get("update_key"))
        self.state: dict = {}
        self.unsent = False
        self.last_report = 0.0
        self.last_cancel_check = 0.0
        self.last_renewal = 0.0

    def update(self, changes: dict) -> None:
        """Takes a change of the task's state; a new state is reported at once, progress at most every interval"""
        self.state.update(changes)
        self.unsent = True
        if "task_state" in changes:
            self.report()
        else:
            self.report_due()

    def report_due(self) -> None:
        """Reports what changed, if the last report (or attempt) was an interval ago"""
        if time.monotonic() - self.last_report >= self.interval_seconds:
            self.report()

    def report(self) -> bool:
        """Puts the task's state into its object, if anything changed; whether it is there"""
        if not self.unsent:
            return True
        self.renew_links_if_expiring()
        # an attempt counts as a report for the interval, so a failing storage is not hammered every second
        self.last_report = time.monotonic()
        body = json.dumps({"task_id": self.task_id, "update": self.state}).encode()
        key = f"{self.links['progress']['prefix']}task_{self.task_id:04d}.json"
        data, content_type = multipart(dict(self.links["progress"]["fields"], key=key), body)
        status = self.send(self.links["progress"]["url"], "POST", data, {"Content-Type": content_type})
        # 400 or 403: an expired or otherwise refused link - new links, then one more try
        if status in (400, 403) and self.renew_links():
            data, content_type = multipart(dict(self.links["progress"]["fields"], key=key), body)
            status = self.send(self.links["progress"]["url"], "POST", data, {"Content-Type": content_type})
        if status in (200, 201, 204):
            self.unsent = False
        return not self.unsent

    def report_final(self) -> None:
        """The task's last state, retried for a while: without it the task would stay running"""
        for attempt in range(FINAL_ATTEMPTS):
            if self.report():
                return
            if attempt < FINAL_ATTEMPTS - 1:
                time.sleep(FINAL_RETRY_SECONDS)
        logging.error("The final state of task %d could not be stored", self.task_id)

    def cancelled(self) -> bool:
        """Whether the simulation was cancelled; looked up at most every interval"""
        if time.monotonic() - self.last_cancel_check < self.interval_seconds:
            return False
        self.last_cancel_check = time.monotonic()
        self.renew_links_if_expiring()
        status = self.send(self.links["cancel"], "HEAD")
        if status in (400, 403) and self.renew_links():
            status = self.send(self.links["cancel"], "HEAD")
        return status == 200

    def renew_links_if_expiring(self) -> None:
        """New links a day before these expire"""
        if time.time() > self.links.get("expires", float("inf")) - RENEW_BEFORE_SECONDS:
            self.renew_links()

    def renew_links(self) -> bool:
        """New signed links from the backend, at most every RENEW_INTERVAL_SECONDS (a refused link may be a
        configuration error, which new links would not fix); the file gets them for tasks that start later
        """
        if time.monotonic() - self.last_renewal < RENEW_INTERVAL_SECONDS and self.last_renewal:
            return False
        self.last_renewal = time.monotonic()
        payload = json.dumps({"simulation_id": self.backend["sim_id"], "update_key": self.backend["update_key"]})
        req = request.Request(
            f"{self.backend['backend_url']}/tasks/links",
            payload.encode(),
            {"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, context=CONTEXT, timeout=60) as response:  # skipcq: BAN-B310
                links = json.load(response)["links"]
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("New links refused: %s", err)
            return False
        self.links = links
        temporary = self.links_path.with_suffix(f".{self.task_id}.tmp")
        temporary.write_text(json.dumps(dict(links, update_key=self.backend["update_key"])))
        temporary.replace(self.links_path)
        return True

    @staticmethod
    def send(url: str, method: str, data: Optional[bytes] = None, headers: Optional[dict] = None) -> int:
        """One request to storage; the status, or 0 when it could not be reached"""
        req = request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with request.urlopen(req, context=CONTEXT, timeout=60) as response:  # skipcq: BAN-B310
                return response.status
        except error.HTTPError as http_error:
            return http_error.code
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("%s %s failed: %s", method, url.split("?")[0], err)
            return 0


def pack(work_dir: Path, archive: Path) -> bool:
    """Packs the simulator's result files into the archive; False when there are none, or when the simulator began
    rewriting one meanwhile (its next save)
    """
    files = sorted(work_dir.glob("*.bdo"))
    before = [(path.stat().st_mtime_ns, path.stat().st_size) for path in files]
    # the fastest compression: it saves most where the results are sparse, and the simulator shares the core
    try:
        with tarfile.open(str(archive), "w:gz", compresslevel=1) as tar:
            for path in files:
                tar.add(str(path), arcname=path.name)
    except OSError:
        # a file the simulator truncated while it was read
        return False
    return bool(files) and before == [(path.stat().st_mtime_ns, path.stat().st_size) for path in files]


class Saver:
    """Puts the simulator's result files into storage after it saved them, for the partial results"""

    def __init__(self, work_dir: Path, reporter: Reporter):
        """work_dir: where the simulator writes its result files; reporter: the task's, with the links and state"""
        self.work_dir = work_dir
        self.reporter = reporter
        self.last_time = float("-inf")
        self.last_primaries = 0

    def saved(self) -> None:
        """The simulator wrote all its result files: put into storage when due, and its primaries reported; a
        failure loses only this save
        """
        simulated = self.reporter.state.get("simulated_primaries", 0)
        requested = self.reporter.state.get("requested_primaries", 0)
        # the last save, at the end, is collected with the others; jobs submitted before saves went to storage have
        # no links for them
        if not 0 < simulated < requested or time.monotonic() - self.last_time < SAVE_SECONDS:
            return
        if "saves" not in self.reporter.links:
            return
        if simulated - self.last_primaries < SAVE_GROWTH * requested:
            return
        self.last_time = time.monotonic()
        try:
            sent = self.send()
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("Sending the save at %d primaries failed: %s", simulated, err)
            return
        if sent:
            self.last_primaries = simulated
            self.reporter.update({"saved_primaries": simulated})

    def send(self) -> bool:
        """Packs the result files and puts them into the task's object; whether they are there"""
        archive = self.work_dir / "yaptide_save.tar.gz"
        try:
            if not pack(self.work_dir, archive):
                logging.info("Save skipped: no result files, or the next save began")
                return False
            size = archive.stat().st_size
            if size > self.reporter.links.get("saves", {}).get("max_bytes", 0):
                logging.info("Save of %d bytes is too large for partial results", size)
                return False
            self.reporter.renew_links_if_expiring()
            status = self.put(archive, size)
            # 400 or 403: an expired or otherwise refused link - new links, then one more try
            if status in (400, 403) and self.reporter.renew_links():
                status = self.put(archive, size)
            return status in (200, 201, 204)
        finally:
            if archive.exists():
                archive.unlink()

    def put(self, archive: Path, size: int) -> int:
        """One upload of the archive, read from the file as it is sent; the status, 0 without a link"""
        url = self.reporter.links.get("saves", {}).get("urls", {}).get(str(self.reporter.task_id))
        if not url:
            return 0
        with open(str(archive), "rb") as body:
            headers = {"Content-Length": str(size), "Content-Type": "application/gzip"}
            return self.reporter.send(url, "PUT", body, headers)


def running(pid: int) -> bool:
    """Whether the simulator still runs"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop(pid: int) -> None:
    """Stops the simulator: politely first, then for good"""
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(STOP_SECONDS):
            if not running(pid):
                return
            time.sleep(1)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def find_log(find: Callable[[], Optional[Path]], pid: int, poll_seconds: float) -> Optional[Path]:
    """The simulator's log, once it exists; None if the simulator ended without one"""
    while True:
        path = find()
        if path is not None:
            return path
        if not running(pid):
            return find()
        time.sleep(poll_seconds)


def watch(  # skipcq: PY-R1000
    find: Callable[[], Optional[Path]],
    parse: Callable[[str], Optional[dict]],
    pid: int,
    reporter: Reporter,
    poll_seconds: float = 1,
    saved: Optional[Callable[[], None]] = None,
) -> None:
    """Follows the simulator's log until it ends or the simulation is cancelled, reporting the task's state;
    saved is called when SHIELD-HIT12A has saved all its result files
    """
    path = find_log(find, pid, poll_seconds)
    if path is None:
        reporter.update({"task_state": "FAILED", "end_time": now()})
        return
    with open(path) as log:  # skipcq: PTC-W6004
        while True:
            line = log.readline()
            if line:
                if saved and re.search(SAVED_MATCH, line):
                    saved()
                update = parse(line)
                if update:
                    reporter.update(update)
                    if update.get("task_state") == "COMPLETED":
                        return
                continue
            if reporter.cancelled():
                stop(pid)
                reporter.update({"task_state": "CANCELED", "end_time": now()})
                return
            if not running(pid):
                # the simulator ended: what it wrote last decides, a run that never completed failed
                for last_line in log:
                    update = parse(last_line)
                    if update:
                        reporter.update(update)
                        if update.get("task_state") == "COMPLETED":
                            return
                reporter.update({"task_state": "FAILED", "end_time": now()})
                return
            reporter.report_due()
            time.sleep(poll_seconds)


def fluka_log(work_dir: Path) -> Callable[[], Optional[Path]]:
    """FLUKA writes its output into a directory named after its process"""
    return lambda: next(work_dir.glob("fluka_*/*001.out"), None)


def main(args) -> None:
    """Watches one task"""
    reporter = Reporter(
        Path(args.links),
        args.task_id,
        # one report and one cancel check per task at most every 15 s, less often with many tasks: about 10 a
        # second of each in all
        max(15.0, args.ntasks / 10),
        {"sim_id": args.sim_id, "update_key": args.update_key, "backend_url": args.backend_url},
    )
    if args.simulator == "fluka":
        watch(fluka_log(Path(args.work_dir)), FlukaParser(), args.pid, reporter)
    else:
        log_path = Path(args.filepath)
        saver = Saver(log_path.parent, reporter)
        watch(lambda: log_path if log_path.exists() else None, shieldhit_update, args.pid, reporter, saved=saver.saved)
    reporter.report_final()


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", choices=("shieldhit", "fluka"), default="shieldhit")
    parser.add_argument("--filepath", help="SHIELD-HIT12A's log")
    parser.add_argument("--work_dir", help="the task's directory, where FLUKA runs")
    parser.add_argument("--pid", type=int, required=True, help="the simulator's process")
    parser.add_argument("--links", required=True, help="storage_links.json of the simulation")
    parser.add_argument("--ntasks", type=int, default=1)
    parser.add_argument("--sim_id", type=int, required=True)
    parser.add_argument("--task_id", type=int, required=True)
    # by default from the links file: a command line is visible to other users of the node
    parser.add_argument("--update_key")
    parser.add_argument("--backend_url", required=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main(parser.parse_args())
