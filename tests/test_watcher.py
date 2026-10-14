"""The watcher of an HPC task: progress into storage with a signed policy, a cancel from storage stops the simulator"""

import email
import json
import subprocess
import sys
import threading
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
    expired_once = False
    renewals = 0

    def do_POST(self):
        """A progress report (multipart, as an S3 POST policy upload) or a request for new links"""
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/tasks/links":
            FakeStorage.renewals += 1
            return self.answer(200, {"links": links(self.server.server_address[1])})
        if FakeStorage.expired_once:
            FakeStorage.expired_once = False
            return self.answer(403, {})
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStorage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    (tmp_path / "storage_links.json").write_text(json.dumps(links(port)))
    monkeypatch.setattr(watcher, "CANCEL_CHECK_SECONDS", 0)
    monkeypatch.setattr(watcher, "STOP_SECONDS", 1)
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
    """After a week the signed links expire; new ones come from the backend and are shared through the file"""
    tmp_path, backend_url = storage
    FakeStorage.expired_once = True
    task = reporter(tmp_path, backend_url)

    task.update({"task_state": "RUNNING"})

    assert FakeStorage.renewals == 1
    assert report()["task_state"] == "RUNNING"
    assert json.loads((tmp_path / "storage_links.json").read_text())["progress"]["fields"] == {"policy": "signed"}


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
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
