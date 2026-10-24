"""The watcher of an HPC task: progress into storage with a signed policy, a cancel from storage stops the simulator"""

import email
import io
import os
import shutil
import json
import signal
import subprocess
import sys
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from yaptide.batch import watcher

SHIELDHIT_RUN = """  Requested number of primaries NSTAT      : 1000
     Primary particle no.         500      ETR:   0 hours  0 minutes  4 seconds
     Primary particle no.        1000      ETR:   0 hours  0 minutes  0 seconds
   Run time:   0 hours  0 minutes  1 seconds     prim/sec:        100
"""


class FakeStorage(BaseHTTPRequestHandler):
    """The bucket as the jobs see it: POST uploads under the policy's prefix, HEAD of the cancel object, and the
    backend's endpoint for new links
    """

    objects: dict = {}
    cancelled = False
    # Garage answers an expired link with 400; a link signed with a wrong secret gets 403 every time
    expired_once = False
    always_refused = False
    down_for = 0
    renewals = 0
    renewal_keys: list = []

    def do_POST(self):
        """A progress report (multipart, as an S3 POST policy upload) or a request for new links"""
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/tasks/links":
            FakeStorage.renewals += 1
            FakeStorage.renewal_keys.append(json.loads(data)["update_key"])
            return self.answer(200, {"links": links(self.server.server_address[1])})
        if FakeStorage.down_for > 0:
            FakeStorage.down_for -= 1
            return self.answer(503, {})
        if FakeStorage.always_refused:
            return self.answer(403, {})
        if FakeStorage.expired_once:
            FakeStorage.expired_once = False
            return self.answer(400, {})
        message = email.message_from_bytes(f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + data)
        fields = {
            part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.get_payload()
        }
        key = fields["key"].decode()
        if fields.get("policy") != b"signed" or not key.startswith("simulations/7/progress/"):
            return self.answer(403, {})
        FakeStorage.objects[key] = json.loads(fields["file"])
        return self.answer(204, None)

    def do_PUT(self):
        """A save, with its signed link"""
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if FakeStorage.down_for > 0:
            FakeStorage.down_for -= 1
            return self.answer(503, {})
        if FakeStorage.expired_once:
            FakeStorage.expired_once = False
            return self.answer(400, {})
        path, _, query = self.path.partition("?")
        if query != "signed":
            return self.answer(403, {})
        FakeStorage.objects[path] = data
        return self.answer(200, None)

    def do_HEAD(self):
        """The cancel object exists once the simulation is cancelled"""
        self.send_response(200 if FakeStorage.cancelled else 404)
        self.end_headers()

    def answer(self, code: int, content) -> None:
        """JSON answer, or none"""
        self.send_response(code)
        self.end_headers()
        if content is not None:
            self.wfile.write(json.dumps(content).encode())

    def log_message(self, *_):  # skipcq: PYL-R0201
        """Keeps the test output quiet"""


def links(port: int) -> dict:
    """storage_links.json as the submit writes it"""
    return {
        "progress": {
            "url": f"http://127.0.0.1:{port}/bucket",
            "fields": {"policy": "signed"},
            "prefix": "simulations/7/progress/",
        },
        "cancel": f"http://127.0.0.1:{port}/bucket/simulations/7/cancel",
    }


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """The fake storage running, the links file written, and the watcher's waits shortened"""
    FakeStorage.objects, FakeStorage.cancelled, FakeStorage.expired_once, FakeStorage.renewals = {}, False, False, 0
    FakeStorage.always_refused, FakeStorage.down_for, FakeStorage.renewal_keys = False, 0, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStorage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    (tmp_path / "storage_links.json").write_text(json.dumps(links(port)))
    monkeypatch.setattr(watcher, "STOP_SECONDS", 1)
    monkeypatch.setattr(watcher, "FINAL_RETRY_SECONDS", 0)
    yield tmp_path, f"http://127.0.0.1:{port}"
    server.shutdown()


def simulator(log: Path, lines: str, seconds_after: float) -> subprocess.Popen:
    """A process writing a simulator's log, then running on for a while"""
    script = f"import time, pathlib; pathlib.Path({str(log)!r}).write_text({lines!r}); time.sleep({seconds_after})"
    process = subprocess.Popen([sys.executable, "-c", script])
    # reaped as soon as it ends, as the job's shell does on the cluster - a zombie would still look alive
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def reporter(tmp_path: Path, backend_url: str) -> watcher.Reporter:
    """Task 3's reporter, reporting at once"""
    backend = {"sim_id": 7, "update_key": "key", "backend_url": backend_url}
    return watcher.Reporter(tmp_path / "storage_links.json", 3, 0, backend)


def report(key: str = "simulations/7/progress/task_0003.json") -> dict:
    """What the storage holds for task 3"""
    return FakeStorage.objects[key]["update"]


def test_progress_and_completion_go_into_the_task_object(storage):
    """A run's states and primaries end up in the task's own object, under the policy's prefix"""
    tmp_path, backend_url = storage
    log = tmp_path / "shieldhit_0003.log"
    process = simulator(log, SHIELDHIT_RUN, 0)

    watcher.watch(
        lambda: log if log.exists() else None, watcher.shieldhit_update, process.pid, reporter(tmp_path, backend_url)
    )

    assert report()["task_state"] == "COMPLETED"
    assert report()["requested_primaries"] == 1000
    assert report()["simulated_primaries"] == 1000


def test_cancel_in_storage_stops_the_simulator(storage):
    """The simulator is killed and the task reports CANCELED"""
    tmp_path, backend_url = storage
    log = tmp_path / "shieldhit_0003.log"
    process = simulator(log, SHIELDHIT_RUN.splitlines(keepends=True)[0], 600)
    FakeStorage.cancelled = True

    watcher.watch(
        lambda: log if log.exists() else None, watcher.shieldhit_update, process.pid, reporter(tmp_path, backend_url)
    )

    assert not watcher.running(process.pid)
    assert report()["task_state"] == "CANCELED"


def test_simulator_ending_without_completing_fails_the_task(storage):
    """A simulator that died mid-run leaves the task FAILED, not running forever"""
    tmp_path, backend_url = storage
    log = tmp_path / "shieldhit_0003.log"
    process = simulator(log, SHIELDHIT_RUN.splitlines(keepends=True)[0], 0)

    watcher.watch(
        lambda: log if log.exists() else None, watcher.shieldhit_update, process.pid, reporter(tmp_path, backend_url)
    )

    assert report()["task_state"] == "FAILED"


def test_expired_links_are_renewed_by_the_backend(storage):
    """After a week the signed links expire (Garage answers 400); new ones come from the backend, also for tasks
    that start later
    """
    tmp_path, backend_url = storage
    FakeStorage.expired_once = True
    task = reporter(tmp_path, backend_url)

    task.update({"task_state": "RUNNING"})

    assert FakeStorage.renewals == 1
    assert report()["task_state"] == "RUNNING"
    assert json.loads((tmp_path / "storage_links.json").read_text())["progress"]["fields"] == {"policy": "signed"}


def test_update_key_comes_from_the_links_file(storage):
    """Without --update_key (a command line other users of the node see) the key is read from the links file, and
    kept there when the links are renewed
    """
    tmp_path, backend_url = storage
    links_file = tmp_path / "storage_links.json"
    links_file.write_text(json.dumps({**json.loads(links_file.read_text()), "update_key": "from-file"}))
    FakeStorage.expired_once = True
    task = watcher.Reporter(links_file, 3, 0, {"sim_id": 7, "update_key": None, "backend_url": backend_url})

    task.update({"task_state": "RUNNING"})

    assert FakeStorage.renewal_keys == ["from-file"]
    assert json.loads(links_file.read_text())["update_key"] == "from-file"


def test_progress_is_reported_at_most_every_few_seconds(storage):
    """Primaries changing every second are reported at the interval; a new state goes at once"""
    tmp_path, backend_url = storage
    task = watcher.Reporter(
        tmp_path / "storage_links.json", 3, 60, {"sim_id": 7, "update_key": "k", "backend_url": backend_url}
    )

    task.update({"task_state": "RUNNING"})
    task.update({"simulated_primaries": 10})
    task.update({"simulated_primaries": 20})
    assert report().get("simulated_primaries") is None
    task.update({"task_state": "COMPLETED"})

    assert report() == {"task_state": "COMPLETED", "simulated_primaries": 20}


def test_fluka_output_gives_progress_and_completion():
    """FLUKA's progress lines count only after NEXT SEEDS; the end banner completes the task"""
    parse = watcher.FlukaParser()
    assert parse("    10000    0.5    0.2    0.1    0.3    0.0\n") is None  # before the run
    assert parse(" NEXT SEEDS: 1 2 3\n") is None
    first = parse("    100    900    1.0E-03    5.0E-03    1.0E-01    1.0E+00\n")
    assert (first["task_state"], first["requested_primaries"], first["simulated_primaries"]) == ("RUNNING", 1000, 100)
    assert parse("    500    500    1.0E-03    5.0E-03    1.0E-01    1.0E+00\n") == {"simulated_primaries": 500}
    end = parse(" * ======                    End of FLUKA 4-4.0 run                    ====== *\n")
    assert (end["task_state"], end["simulated_primaries"]) == ("COMPLETED", 1000)


def test_watcher_runs_with_the_standard_library_only(tmp_path):
    """The cluster's Python has no packages of ours: the script imports nothing beyond the standard library"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", f"import runpy; runpy.run_path({str(Path(watcher.__file__))!r})"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_links_are_renewed_a_day_before_they_expire(storage):
    """No report is lost to an expiry: new links are asked for in advance"""
    tmp_path, backend_url = storage
    links_file = tmp_path / "storage_links.json"
    links_file.write_text(json.dumps({**json.loads(links_file.read_text()), "expires": int(time.time()) + 3600}))

    reporter(tmp_path, backend_url).update({"task_state": "RUNNING"})

    assert FakeStorage.renewals == 1


def test_refused_links_are_not_renewed_in_a_loop(storage):
    """A link refused for another reason (e.g. a wrong key) gets one renewal, not one per attempt"""
    tmp_path, backend_url = storage
    FakeStorage.always_refused = True
    task = reporter(tmp_path, backend_url)

    task.update({"task_state": "RUNNING"})
    task.update({"task_state": "RUNNING", "simulated_primaries": 5})

    assert FakeStorage.renewals == 1


def test_final_state_waits_for_the_storage(storage):
    """A restart of the storage when the task ends does not leave it running forever"""
    tmp_path, backend_url = storage
    task = reporter(tmp_path, backend_url)
    FakeStorage.down_for = 3

    task.update({"task_state": "COMPLETED"})
    task.report_final()

    assert report()["task_state"] == "COMPLETED"


# a partial script standing in for the one the submit writes: notes each run, then frees the lock as the real one does
PARTIAL_SCRIPT = 'echo run >> "$(dirname "$0")/merges"; rmdir "$(dirname "$0")/partial.lock"\n'


def saves(work_dir: Path) -> dict:
    """The task's saves kept aside: directory name -> the result files in it (name -> content)"""
    saves_dir = work_dir / "saves"
    if not saves_dir.exists():
        return {}
    return {
        save.name: {path.name: path.read_bytes() for path in save.iterdir()} for save in sorted(saves_dir.iterdir())
    }


def merges(root: Path) -> int:
    """Runs of the partial script so far, once they ended"""
    for _ in range(100):
        if not (root / "partial.lock").exists():
            break
        time.sleep(0.05)
    return len((root / "merges").read_text().split()) if (root / "merges").exists() else 0


def saver(tmp_path: Path, backend_url: str, simulated: int, script: str = PARTIAL_SCRIPT) -> watcher.Saver:
    """Task 3's saver, with 1000 primaries requested and some simulated, a result file in its directory and the
    partial script next to the links
    """
    (tmp_path / "dose.bdo").write_bytes(b"dose")
    (tmp_path / "partial_script.sh").write_text(script)
    task = reporter(tmp_path, backend_url)
    task.state.update({"requested_primaries": 1000, "simulated_primaries": simulated})
    return watcher.Saver(tmp_path, task)


def test_saves_are_kept_aside_and_merged_on_the_cluster(storage):
    """A save half way through is copied into the task's saves, named by its primaries, and a partial merge starts;
    the last save at the end is left to the collect. Nothing of it goes into storage
    """
    tmp_path, backend_url = storage
    log = tmp_path / "shieldhit_0003.log"
    (tmp_path / "dose.bdo").write_bytes(b"dose")
    (tmp_path / "partial_script.sh").write_text(PARTIAL_SCRIPT)
    lines = SHIELDHIT_RUN.replace("4 seconds\n", "4 seconds\n  Saved all 1 estimator(s)\n")
    process = simulator(log, lines + "  Saved all 1 estimator(s)\n", 0)
    task = reporter(tmp_path, backend_url)

    watcher.watch(
        lambda: log if log.exists() else None,
        watcher.shieldhit_update,
        process.pid,
        task,
        saved=watcher.Saver(tmp_path, task).saved,
    )

    assert saves(tmp_path) == {"500": {"dose.bdo": b"dose"}}
    assert merges(tmp_path) == 1
    assert report()["task_state"] == "COMPLETED" and "saved_primaries" not in report()
    assert set(FakeStorage.objects) == {"simulations/7/progress/task_0003.json"}


def test_saves_are_kept_at_most_every_minute_and_tenth_the_latest_two(storage, monkeypatch):
    """One save a minute at most, each covering more primaries; the two latest are kept (a merge may still read the
    older one)
    """
    tmp_path, backend_url = storage
    task = saver(tmp_path, backend_url, 100)
    task.saved()
    task.reporter.state["simulated_primaries"] = 300
    task.saved()
    assert list(saves(tmp_path)) == ["100"]  # within the minute

    monkeypatch.setattr(watcher, "SAVE_SECONDS", 0)
    task.reporter.state["simulated_primaries"] = 120
    task.saved()
    assert list(saves(tmp_path)) == ["100"]  # too few new primaries
    for primaries in (300, 500):
        task.reporter.state["simulated_primaries"] = primaries
        task.saved()
    assert list(saves(tmp_path)) == ["300", "500"]


def test_a_save_rewritten_while_copied_is_skipped(storage, monkeypatch):
    """The simulator's next save began while this one was copied: no save kept, no merge, the next save tries"""
    tmp_path, backend_url = storage
    monkeypatch.setattr(watcher, "SAVE_SECONDS", 0)
    task = saver(tmp_path, backend_url, 100)
    copy = shutil.copyfile
    monkeypatch.setattr(
        watcher.shutil, "copyfile", lambda source, target: (copy(source, target), Path(source).write_bytes(b"next"))
    )
    task.saved()
    assert saves(tmp_path) == {} and merges(tmp_path) == 0
    monkeypatch.setattr(watcher.shutil, "copyfile", copy)

    task.saved()
    assert saves(tmp_path) == {"100": {"dose.bdo": b"next"}} and merges(tmp_path) == 1


def test_one_partial_merge_at_a_time_and_not_too_often(storage, monkeypatch):
    """A merge holding the lock (another task's) is not joined, one left by a killed merge is taken over; after a
    merge the next waits PARTIAL_SECONDS
    """
    tmp_path, backend_url = storage
    monkeypatch.setattr(watcher, "SAVE_SECONDS", 0)
    task = saver(tmp_path, backend_url, 100)
    (tmp_path / "partial.lock").mkdir()
    task.saved()
    assert list(saves(tmp_path)) == ["100"] and not (tmp_path / "merges").exists()

    old = time.time() - watcher.PARTIAL_LOCK_SECONDS - 1
    os.utime(tmp_path / "partial.lock", (old, old))
    task.reporter.state["simulated_primaries"] = 200
    task.saved()
    assert merges(tmp_path) == 1

    task.reporter.state["simulated_primaries"] = 300
    task.saved()
    assert merges(tmp_path) == 1  # within PARTIAL_SECONDS
    monkeypatch.setattr(watcher, "PARTIAL_SECONDS", 0)
    task.reporter.state["simulated_primaries"] = 400
    task.saved()
    assert merges(tmp_path) == 2


def test_a_partial_merge_stops_with_its_task(storage):
    """The final results come next: a merge still running when the task ends is stopped and frees the lock"""
    tmp_path, backend_url = storage
    task = saver(tmp_path, backend_url, 100, script="sleep 30\n")
    task.saved()
    assert task.merge.poll() is None and (tmp_path / "partial.lock").is_dir()

    task.stop_merge()

    assert task.merge.poll() is not None and not (tmp_path / "partial.lock").exists()


def test_no_saves_kept_for_jobs_without_the_partial_script(storage):
    """Jobs submitted before the cluster merged partial results have no partial script: nothing is kept"""
    tmp_path, backend_url = storage
    task = saver(tmp_path, backend_url, 100)
    (tmp_path / "partial_script.sh").unlink()

    task.saved()

    assert saves(tmp_path) == {}


def started_task(work_dir: Path, own_group: bool = True) -> subprocess.Popen:
    """A simulator started as the array script does through srun: it records its PID; SLURM makes it lead a process
    group of its own
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        ["sh", "-c", 'echo $$ > simulator.pid && exec "$@"', "sh", "sleep", "600"],
        cwd=work_dir,
        start_new_session=own_group,
    )
    pid_file = work_dir / watcher.SIMULATOR_PID_FILE
    while not pid_file.exists() or not pid_file.read_text().strip():
        time.sleep(0.01)
    return process


@pytest.mark.skipif(not Path("/proc/self/cwd").exists(), reason="reads /proc, as on the cluster's Linux nodes")
def test_a_cancel_stops_the_simulator_without_slurm_only_in_the_tasks_own_directory(tmp_path):
    """The simulator of the task stops; one whose PID file sits in another task's directory, or that does not lead a
    process group of its own, is left alone
    """
    task = started_task(tmp_path / "task_0001")
    other = started_task(tmp_path / "task_0002")
    (tmp_path / "task_0003").mkdir()
    (tmp_path / "task_0003" / watcher.SIMULATOR_PID_FILE).write_text(str(other.pid))
    shared_group = started_task(tmp_path / "task_0004", own_group=False)
    try:
        watcher.stop_task(tmp_path / "task_0003")
        watcher.stop_task(tmp_path / "task_0004")
        assert other.poll() is None and shared_group.poll() is None

        watcher.stop_task(tmp_path / "task_0001")
        assert task.wait(timeout=5) == -signal.SIGTERM
        assert other.poll() is None
    finally:
        for process in (task, other, shared_group):
            process.kill()
