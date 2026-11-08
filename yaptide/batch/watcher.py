"""Follows one simulation task on the cluster: its progress goes into object storage, a cancel stops it.

Runs next to the simulator on the compute node, with the standard library only. The task's state goes into one
small object of its own, at most every few seconds and at once when the state changes; the backend's engine reads
these objects. The result files SHIELD-HIT12A saves along the way are copied aside on the cluster (the task's saves
directory, only the pages partial results carry: bdo_pages.py). Partial results are merged only for the users who
look at them: the backend keeps a small object in storage saying until when someone has the simulation's results
open, and which maps they asked for (result_format.parse_wanted). While someone looks, a watcher now and then starts
the partial script for its task's group, which merges the latest saves of the group, then of all tasks, and uploads
the merged live pages as partial results (merge_groups.py, results_uploader.py); for a map asked for, a watcher starts
the partial script for that page alone. A cancel is an object the backend puts into storage: the watcher checks for it
and kills the simulator. The signed links come in storage_links.json, written at submit; when they expire (after a week),
the watcher asks the backend for new ones.
"""

import argparse
import json
import logging
import os
import re
import shutil
import signal
import ssl
import subprocess
import time
import uuid
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple
from urllib import error, request

try:
    from yaptide.batch import bdo_pages, merge_groups, result_format
except ImportError:  # on a cluster, next to this script
    import bdo_pages
    import merge_groups
    import result_format

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
# where the simulator's process, started by srun, writes its PID, in the task's directory (see the array scripts)
SIMULATOR_PID_FILE = "simulator.pid"
# new links are asked for a day before they expire, and not more often than this
RENEW_BEFORE_SECONDS = 24 * 3600
RENEW_INTERVAL_SECONDS = 600
# the final state is retried for about two minutes, longer than a restart of the storage
FINAL_ATTEMPTS = 6
FINAL_RETRY_SECONDS = 20
# a save is copied aside at most this often (the live merges' interval at least), and once it covers this much more
# of the task's primaries: small results save far more often than that (yaptide/utils/sim_utils.py, MAX_SAVES)
SAVE_SECONDS = result_format.LIVE_MIN_SECONDS
SAVE_GROWTH = 0.001
# the pages a save is copied with: the ones of partial results (volumes and particle lists wait for the end)
SAVED_MODES = {result_format.LIVE, result_format.ON_DEMAND}
# saves kept of each task: the latest, and the one before for a partial merge still reading it
KEPT_SAVES = 2
# the script merging the latest saves of a group of tasks into partial results, next to the links file; one runs at a
# time for each group (it holds the group's lock, merge_groups.py), at most every live interval for the group
# (result_format.live_interval, from the size of a save; PARTIAL_SECONDS before the first)
PARTIAL_SCRIPT = "partial_script.sh"
PARTIAL_STAMP = merge_groups.PARTIAL_STAMP
PARTIAL_SECONDS = result_format.LIVE_MIN_SECONDS
# a lock untouched for this long was left by a partial merge that was killed (its task ended, it ran out of memory)
PARTIAL_LOCK_SECONDS = merge_groups.LOCK_SECONDS
# a merge of pages asked for starts at most this long after the last one ended, while the request stays (one failed,
# or the backend has not taken the pages off the list yet)
ON_DEMAND_SECONDS = result_format.LIVE_MIN_SECONDS


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
        f"Content-Type: application/json\r\n\r\n".encode() + body + b"\r\n"
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
        self.last_wanted_check = float("-inf")
        self.last_renewal = 0.0
        # the wanted object as last read: its ETag, and live_until and the pages asked for (result_format.parse_wanted)
        self.wanted_etag: Optional[str] = None
        self.wanted_state: tuple = (0.0, frozenset())
        # the finish object as last read: its ETag, and the tasks the user asked to finish early
        self.last_finish_check = float("-inf")
        self.finish_etag: Optional[str] = None
        self.finish_tasks: frozenset = frozenset()

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

    def wanted(self) -> tuple:
        """What the users look at (result_format.parse_wanted): live_until and the pages asked for; read again at most
        every interval, a conditional GET (an unchanged object is not sent again). The last known state when storage
        cannot be reached; nothing for links without the object (a job submitted before)
        """
        if "wanted" not in self.links or time.monotonic() - self.last_wanted_check < self.interval_seconds:
            return self.wanted_state
        self.last_wanted_check = time.monotonic()
        self.renew_links_if_expiring()
        status, body, etag = self.fetch(self.links["wanted"], self.wanted_etag)
        if status in (400, 403) and self.renew_links():
            status, body, etag = self.fetch(self.links["wanted"], self.wanted_etag)
        if status == 200:
            self.wanted_state, self.wanted_etag = result_format.parse_wanted(body), etag
        elif status == 404:
            # no one looked at the simulation yet, or its results are final
            self.wanted_state, self.wanted_etag = (0.0, frozenset()), None
        return self.wanted_state

    def finish_requested(self) -> bool:
        """Whether the user asked to finish this task early (the finish object names it); read again at most every
        interval, a conditional GET. False when storage cannot be reached or for links without the object
        """
        if "finish" not in self.links or time.monotonic() - self.last_finish_check < self.interval_seconds:
            return self.task_id in self.finish_tasks
        self.last_finish_check = time.monotonic()
        self.renew_links_if_expiring()
        status, body, etag = self.fetch(self.links["finish"], self.finish_etag)
        if status in (400, 403) and self.renew_links():
            status, body, etag = self.fetch(self.links["finish"], self.finish_etag)
        if status == 200:
            try:
                tasks = json.loads(body).get("tasks", [])
                self.finish_tasks = frozenset(int(task) for task in tasks)
                self.finish_etag = etag
            except (ValueError, TypeError, AttributeError):
                logging.warning("A finish object that cannot be read: %r", body[:200])
        elif status == 404:
            self.finish_tasks, self.finish_etag = frozenset(), None
        return self.task_id in self.finish_tasks

    @staticmethod
    def fetch(url: str, etag: Optional[str] = None) -> Tuple[int, bytes, Optional[str]]:
        """A GET from storage, conditional on the ETag: status, body and ETag; 0 when storage could not be reached"""
        headers = {"If-None-Match": etag} if etag else {}
        try:
            with request.urlopen(  # skipcq: BAN-B310
                request.Request(url, headers=headers), context=CONTEXT, timeout=60
            ) as response:
                return response.status, response.read(1 << 20), response.headers.get("ETag")
        except error.HTTPError as http_error:
            return http_error.code, b"", None
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("GET %s failed: %s", url.split("?")[0], err)
            return 0, b"", None

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


def copy_save(work_dir: Path, target: Path) -> bool:
    """Copies the simulator's result files into target, with only the pages partial results carry (SAVED_MODES: a
    volume is not copied at every save); False when there are none, when the simulator began rewriting one meanwhile
    (its next save), or when a file came out cut short (seen on a cluster node busy writing other tasks' saves)
    """
    files = sorted(work_dir.glob("*.bdo"))
    before = [(path.stat().st_mtime_ns, path.stat().st_size) for path in files]
    target.mkdir(parents=True)
    try:
        for path in files:
            bdo_pages.copy_pages(
                path,
                target / path.name,
                lambda info: result_format.partial_mode(info.dimensions, info.mcpl) in SAVED_MODES,
            )
    except bdo_pages.BdoError as err:
        logging.info("A result file is not whole: %s", err)
        return False
    return bool(files) and before == [(path.stat().st_mtime_ns, path.stat().st_size) for path in files]


def live_bytes(directory: Path, fallback: int) -> int:
    """Bytes of the values of the live pages (points and lines) in a save's result files: what a live merge reads of
    it; fallback when a file cannot be walked
    """
    try:
        return sum(
            info.data_bytes
            for path in directory.glob("*.bdo")
            for info in bdo_pages.pages_of(path)
            if result_format.partial_mode(info.dimensions, info.mcpl) == result_format.LIVE
        )
    except (OSError, bdo_pages.BdoError):
        return fallback


class Saver:
    """Copies the simulator's result files aside after it saved them, and starts merges of the latest saves of all
    tasks into partial results while someone looks at them: of the live pages, and of the maps asked for
    """

    def __init__(self, work_dir: Path, reporter: Reporter, root_dir: Optional[Path] = None, n_tasks: int = 1):
        """work_dir: where the simulator writes its result files; reporter: the task's, with its state; root_dir: the
        simulation's directory, with the partial script (the links file's); n_tasks: the simulation's tasks
        """
        self.work_dir = work_dir
        self.reporter = reporter
        self.root_dir = root_dir if root_dir is not None else reporter.links_path.parent
        self.n_tasks = n_tasks
        self.last_time = float("-inf")
        self.last_primaries = 0
        # the live partial merge this watcher started, and for which group (the task's, once planned); the merge of
        # pages asked for
        self.merge: Optional[subprocess.Popen] = None
        self.group: Optional[int] = None
        self.on_demand: Optional[subprocess.Popen] = None
        # seconds between live merges, from the size of a save (all its result files)
        self.interval = PARTIAL_SECONDS

    def watched(self) -> bool:
        """Whether someone looks at the simulation's results now (the wanted object's live_until)"""
        live_until, _ = self.reporter.wanted()
        return time.time() < live_until

    def saved(self) -> None:
        """The simulator wrote all its result files: copied aside when due (a merge asked for later needs every
        task's latest save), then a live merge when someone looks and one is due; a failure loses only this save
        """
        simulated = self.reporter.state.get("simulated_primaries", 0)
        requested = self.reporter.state.get("requested_primaries", 0)
        # the last save, at the end, is collected with the others; jobs submitted before the partial script have none
        if not 0 < simulated < requested or time.monotonic() - self.last_time < SAVE_SECONDS:
            return
        if not (self.root_dir / PARTIAL_SCRIPT).exists():
            return
        if simulated - self.last_primaries < SAVE_GROWTH * requested:
            return
        self.last_time = time.monotonic()
        try:
            kept = self.keep(simulated)
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("Keeping the save at %d primaries failed: %s", simulated, err)
            return
        if kept:
            self.last_primaries = simulated
            # the groups are planned from the size of the whole result files (the final merges read them whole): the
            # same for every task
            save_bytes = merge_groups.files_size(self.work_dir)
            # a live merge reads only the live pages of the saves (it skips the others): its interval goes by them
            self.interval = result_format.live_interval(live_bytes(self.work_dir / "saves" / str(simulated), save_bytes))
            size = merge_groups.plan(self.root_dir, self.n_tasks, save_bytes)
            self.group = merge_groups.group_of(self.reporter.task_id, size, self.n_tasks)
            if self.watched():
                self.start_merge(self.group)

    def keep(self, primaries: int) -> bool:
        """Copies the result files into the task's saves, named by their primaries, and removes all but the latest
        KEPT_SAVES; whether the save is there whole (a merge takes only whole ones, a directory named by a number)
        """
        saves = self.work_dir / "saves"
        partial = saves / f".{primaries}"
        shutil.rmtree(str(partial), ignore_errors=True)
        if not copy_save(self.work_dir, partial):
            logging.info("Save skipped: no result files, or the next save began")
            shutil.rmtree(str(partial), ignore_errors=True)
            return False
        partial.rename(saves / str(primaries))
        whole = sorted((path for path in saves.iterdir() if path.name.isdigit()), key=lambda path: int(path.name))
        for old in whole[:-KEPT_SAVES]:
            shutil.rmtree(str(old), ignore_errors=True)
        return True

    def start_merge(self, group: int = 0) -> None:
        """Starts the live partial script for the task's group unless a merge of the group runs (this watcher's or
        another's, holding the group's lock) or one started within the live interval
        """
        if self.merge is not None and self.merge.poll() is None:
            return
        self.merge = None
        stamp, lock = self.root_dir / f"{PARTIAL_STAMP}.{group}", merge_groups.lock_path(self.root_dir, group)
        try:
            if time.time() - stamp.stat().st_mtime < self.interval:
                return
        except FileNotFoundError:
            pass
        try:
            if not merge_groups.live_merge_due(self.root_dir, group, self.n_tasks):
                return
        except OSError as err:
            logging.info("Could not tell whether a live merge is due, starting one: %s", err)
        if not merge_groups.take_lock(lock, PARTIAL_LOCK_SECONDS):
            return
        stamp.touch()
        self.merge = self.start_script(lock, str(group), str(self.interval))
        self.group = group

    def idle(self) -> None:
        """Between the simulator's log lines: while someone looks, a live merge when one is due (so a user who just
        opened the results does not wait for the next save); a merge of the pages asked for, unless one runs (this
        watcher's or another's) or one ended within ON_DEMAND_SECONDS
        """
        # a task without a save yet: the others' watchers take it
        if self.last_primaries == 0 or self.group is None or not (self.root_dir / PARTIAL_SCRIPT).exists():
            return
        checked = self.reporter.last_wanted_check
        live_until, pages = self.reporter.wanted()
        if self.reporter.last_wanted_check == checked:
            # nothing read now: the merges are started at most once per read of the wanted object
            return
        if time.time() < live_until:
            self.start_merge(self.group)
        if pages:
            self.start_pages(pages)

    def start_pages(self, pages) -> None:
        """Starts the partial script for the pages asked for ((estimator, page number) pairs), unless a merge of
        pages runs or one ended within ON_DEMAND_SECONDS
        """
        if self.on_demand is not None and self.on_demand.poll() is None:
            return
        self.on_demand = None
        stamp = self.root_dir / f"{PARTIAL_STAMP}.{merge_groups.ON_DEMAND_LOCK}"
        lock = merge_groups.lock_path(self.root_dir, merge_groups.ON_DEMAND_LOCK)
        try:
            if time.time() - stamp.stat().st_mtime < ON_DEMAND_SECONDS:
                return
        except FileNotFoundError:
            pass
        if not merge_groups.take_lock(lock, PARTIAL_LOCK_SECONDS):
            return
        stamp.touch()
        self.on_demand = self.start_script(
            lock, merge_groups.ON_DEMAND_LOCK, str(self.interval), result_format.pages_argument(pages)
        )

    def start_script(self, lock: Path, *arguments: str) -> Optional[subprocess.Popen]:
        """Starts the partial script holding the lock (it frees it); the lock is freed when the script fails to
        start
        """
        log = open(str(self.work_dir / "partial_merge.log"), "ab")  # skipcq: PTC-W6004
        try:
            # a process group of its own, stopped as a whole with the task (the merge runs in a child of the script)
            return subprocess.Popen(
                ["bash", str(self.root_dir / PARTIAL_SCRIPT), *arguments],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as err:
            logging.warning("The partial merge did not start: %s", err)
            merge_groups.free_lock(lock)
            return None
        finally:
            log.close()

    def stop_merge(self) -> None:
        """Stops the partial merges this watcher started, when the task ends: final results come next. The locks
        they held are freed
        """
        for merge, kind in ((self.merge, result_format.LIVE), (self.on_demand, result_format.ON_DEMAND)):
            if merge is None or merge.poll() is not None:
                continue
            try:
                os.killpg(merge.pid, signal.SIGTERM)
                try:
                    merge.wait(STOP_SECONDS)
                except subprocess.TimeoutExpired:
                    os.killpg(merge.pid, signal.SIGKILL)
                    merge.wait()
            except ProcessLookupError:
                pass
            merge_groups.free_locks(self.root_dir, merge.pid, self.group or 0, kind)


def running(pid: int, kill: Callable[[int, int], None] = os.kill) -> bool:
    """Whether the simulator (or with os.killpg, its process group) still runs"""
    try:
        kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop(pid: int, kill: Callable[[int, int], None] = os.kill) -> None:
    """Stops the simulator (or with os.killpg, its process group): politely first, then for good"""
    try:
        kill(pid, signal.SIGTERM)
        for _ in range(STOP_SECONDS):
            if not running(pid, kill):
                return
            time.sleep(1)
        kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def stop_task(work_dir: Path) -> None:
    """Stops the simulator of this task on this node without SLURM: srun passes its signals on through the SLURM
    controller, which may not answer for minutes. Only the process group the simulator leads (simulator_group)
    """
    group = simulator_group(work_dir)
    if group is not None:
        stop(group, os.killpg)


# a task finished early waits at most this long for the simulator to end a save it is writing: then stopped anyway
FINISH_WAIT_SECONDS = 600
# result files left cut short by a task finished early go here, out of the merges' way
UNFINISHED_DIR = "unfinished"


def simulator_group(work_dir: Path) -> Optional[int]:
    """The process group the simulator of this task leads on this node (SLURM starts each task in one), only while it
    runs in this task's directory: a PID recorded on another node, reused, or of another user is not this one's
    """
    try:
        pid = int((work_dir / SIMULATOR_PID_FILE).read_text())
        cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
        if os.getpgid(pid) != pid or pid == os.getpgrp():
            return None
    except (OSError, ValueError):
        return None
    work_dir = work_dir.resolve()
    # FLUKA runs in a directory of its own inside the task's
    return pid if cwd == work_dir or work_dir in cwd.parents else None


def results_whole(work_dir: Path, log_path: Optional[Path]) -> bool:
    """Whether the simulator's result files are one whole save: there are some, none ends within a page, and none
    changed since the log last did (SHIELD-HIT12A writes its log after a save, and nothing into it while saving)
    """
    files = sorted(work_dir.glob("*.bdo"))
    if not files:
        return False
    try:
        if log_path is not None:
            logged = log_path.stat().st_mtime_ns
            # written after the log: a save under way (a file system keeping whole seconds may show both equal)
            if any(path.stat().st_mtime_ns > logged for path in files):
                return False
        for path in files:
            bdo_pages.pages_of(path)
    except (OSError, bdo_pages.BdoError):
        return False
    return True


def stop_at_whole_save(
    group: int,
    work_dir: Path,
    log_path: Optional[Path],
    kill: Callable[[int, int], None] = os.killpg,
    wait_seconds: float = FINISH_WAIT_SECONDS,
    poll_seconds: float = 1,
) -> bool:
    """Stops the simulator's process group between two saves, so its result files stay its last whole save: frozen
    (SIGSTOP), checked, killed when whole, let go on for a while otherwise (it is writing a save). Whether the files
    are whole; when they are not by wait_seconds, the simulator is stopped all the same
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            kill(group, signal.SIGSTOP)
        except ProcessLookupError:
            return results_whole(work_dir, log_path)
        whole = results_whole(work_dir, log_path)
        if not any(work_dir.glob("*.bdo")):
            # no save begun yet: nothing to wait for
            deadline = float("-inf")
        if not whole and time.monotonic() > deadline:
            # the log may have been quiet since the last save: files that are whole do
            whole = results_whole(work_dir, None)
        if whole or time.monotonic() > deadline:
            try:
                kill(group, signal.SIGKILL)
                kill(group, signal.SIGCONT)
            except ProcessLookupError:
                pass
            return whole
        kill(group, signal.SIGCONT)
        time.sleep(poll_seconds)


def set_aside_unfinished(work_dir: Path, patterns=("*.bdo",)) -> None:
    """Moves result files that are not a whole save out of the merges' way"""
    target = work_dir / UNFINISHED_DIR
    for pattern in patterns:
        for path in work_dir.glob(pattern):
            target.mkdir(exist_ok=True)
            path.rename(target / path.name)


def finish_shieldhit(work_dir: Path, log_path: Path, pid: int, saved_primaries: int) -> dict:
    """Finishes a SHIELD-HIT12A task early: stopped between saves, its last whole save stays as its results (the
    collect merges them) with the primaries of that save; without one, nothing of it is merged and it ends canceled
    """
    group = simulator_group(work_dir)
    whole = stop_at_whole_save(group, work_dir, log_path) if group is not None else False
    stop(pid)
    if group is None:
        whole = results_whole(work_dir, log_path)
    if not whole:
        set_aside_unfinished(work_dir)
        logging.info("Finished early without a whole save: nothing of this task goes into the results")
        return {"task_state": "CANCELED", "end_time": now()}
    logging.info("Finished early at the save of %d primaries", saved_primaries)
    return {
        "task_state": "COMPLETED",
        "simulated_primaries": saved_primaries,
        "finished_early": True,
        "end_time": now(),
    }


# FLUKA ends its cycle when a file of this name appears in its run directory, writing the results of the primaries
# done so far (one cycle per task here)
FLUKA_STOP_FILE = "fluka.stop"


def finish_fluka(work_dir: Path, pid: int, wait_seconds: float = FINISH_WAIT_SECONDS, poll_seconds: float = 1) -> dict:
    """Finishes a FLUKA task early: its stop file ends the cycle with the results so far; stopped all the same if it
    has not ended by wait_seconds, then without results
    """
    for run_dir in work_dir.glob("fluka_*"):
        if run_dir.is_dir():
            (run_dir / FLUKA_STOP_FILE).touch()
    deadline = time.monotonic() + wait_seconds
    while running(pid) and time.monotonic() < deadline:
        time.sleep(poll_seconds)
    ended = not running(pid)
    if not ended:
        stop_task(work_dir)
        stop(pid)
    if ended and any(work_dir.glob("*_fort.*")):
        return {"task_state": "COMPLETED", "finished_early": True, "end_time": now()}
    set_aside_unfinished(work_dir, ("*_fort.*",))
    return {"task_state": "CANCELED", "end_time": now()}


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
    work_dir: Optional[Path] = None,
    idle: Optional[Callable[[], None]] = None,
    finish: Optional[Callable[[int], dict]] = None,
) -> None:
    """Follows the simulator's log until it ends or the simulation is cancelled, reporting the task's state;
    saved is called when SHIELD-HIT12A has saved all its result files. A cancel stops the simulator in the task's
    directory itself, then srun. A request to finish the task early calls finish with the primaries of the last
    save, which stops the simulator and gives the task's final state.
    """
    saved_primaries = 0
    path = find_log(find, pid, poll_seconds)
    if path is None:
        reporter.update({"task_state": "FAILED", "end_time": now()})
        return
    with open(path) as log:  # skipcq: PTC-W6004
        while True:
            line = log.readline()
            if line:
                if re.search(SAVED_MATCH, line):
                    saved_primaries = reporter.state.get("simulated_primaries", saved_primaries)
                    if saved:
                        saved()
                update = parse(line)
                if update:
                    reporter.update(update)
                    if update.get("task_state") == "COMPLETED":
                        return
                continue
            if reporter.cancelled():
                if work_dir:
                    stop_task(work_dir)
                stop(pid)
                reporter.update({"task_state": "CANCELED", "end_time": now()})
                return
            if finish and reporter.finish_requested():
                reporter.update(finish(saved_primaries))
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
            if idle:
                try:
                    idle()
                except Exception as err:  # skipcq: PYL-W0703 - partial results only, the task goes on
                    logging.warning("Looking for a request of the maps failed: %s", err)
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
        work_dir = Path(args.work_dir)
        watch(
            fluka_log(work_dir),
            FlukaParser(),
            args.pid,
            reporter,
            work_dir=work_dir,
            finish=lambda _: finish_fluka(work_dir, args.pid),
        )
    else:
        log_path = Path(args.filepath)
        saver = Saver(log_path.parent, reporter, n_tasks=args.ntasks)
        try:
            watch(
                lambda: log_path if log_path.exists() else None,
                shieldhit_update,
                args.pid,
                reporter,
                saved=saver.saved,
                work_dir=log_path.parent,
                idle=saver.idle,
                finish=lambda primaries: finish_shieldhit(log_path.parent, log_path, args.pid, primaries),
            )
        finally:
            saver.stop_merge()
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
