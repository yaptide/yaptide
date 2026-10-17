"""The watcher of an HPC task: progress into storage with a signed policy, a cancel from storage stops the simulator"""

import email
import io
import json
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
        "saves": {"urls": {"3": f"http://127.0.0.1:{port}/bucket/work/7/task_3.tar.gz?signed"}, "max_bytes": 10**6},
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


SAVE = "/bucket/work/7/task_3.tar.gz"


def saved_files() -> dict:
    """The result files in the task's save in storage: name -> content"""
    with tarfile.open(fileobj=io.BytesIO(FakeStorage.objects[SAVE]), mode="r:gz") as tar:
        return {member.name: tar.extractfile(member).read() for member in tar}


def saver(tmp_path: Path, backend_url: str, simulated: int) -> watcher.Saver:
    """Task 3's saver, with 1000 primaries requested and some simulated, and a result file in its directory"""
    (tmp_path / "dose.bdo").write_bytes(b"dose")
    task = reporter(tmp_path, backend_url)
    task.state.update({"requested_primaries": 1000, "simulated_primaries": simulated})
    return watcher.Saver(tmp_path, task)


def test_saves_go_into_storage_with_their_primaries(storage):
    """A save half way through goes into the task's object, packed; its primaries are reported, the last save at
    the end is left to the collect
    """
    tmp_path, backend_url = storage
    log = tmp_path / "shieldhit_0003.log"
    (tmp_path / "dose.bdo").write_bytes(b"dose")
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

    assert saved_files() == {"dose.bdo": b"dose"}
    assert (report()["saved_primaries"], report()["task_state"]) == (500, "COMPLETED")
    assert not (tmp_path / "yaptide_save.tar.gz").exists()


def test_saves_are_sent_at_most_every_minute_and_tenth(storage, monkeypatch):
    """Saves bound the transfer: one a minute at most, and each covering more primaries"""
    tmp_path, backend_url = storage
    task = saver(tmp_path, backend_url, 100)
    task.saved()
    task.reporter.state["simulated_primaries"] = 300
    task.saved()
    assert task.reporter.state["saved_primaries"] == 100  # within the minute

    monkeypatch.setattr(watcher, "SAVE_SECONDS", 0)
    task.reporter.state["simulated_primaries"] = 120
    task.saved()
    assert task.reporter.state["saved_primaries"] == 100  # too few new primaries
    task.reporter.state["simulated_primaries"] = 300
    task.saved()
    assert task.reporter.state["saved_primaries"] == 300


def test_failed_save_does_not_stop_the_task(storage, monkeypatch):
    """Storage down, a save too large or one rewritten while packed: nothing is reported, the next save tries"""
    tmp_path, backend_url = storage
    monkeypatch.setattr(watcher, "SAVE_SECONDS", 0)
    task = saver(tmp_path, backend_url, 100)
    FakeStorage.down_for = 1
    task.saved()
    assert "saved_primaries" not in task.reporter.state and SAVE not in FakeStorage.objects

    task.reporter.links["saves"]["max_bytes"] = 10
    task.saved()
    assert SAVE not in FakeStorage.objects

    task.reporter.links["saves"]["max_bytes"] = 10**6
    add = tarfile.TarFile.add
    monkeypatch.setattr(
        tarfile.TarFile, "add", lambda tar, name, **kwargs: (add(tar, name, **kwargs), Path(name).write_bytes(b"next"))
    )
    task.saved()
    assert SAVE not in FakeStorage.objects
    monkeypatch.setattr(tarfile.TarFile, "add", add)

    task.saved()
    assert saved_files() == {"dose.bdo": b"next"} and task.reporter.state["saved_primaries"] == 100
    assert not (tmp_path / "yaptide_save.tar.gz").exists()


def test_expired_save_link_is_renewed(storage):
    """A save refused for an expired link goes again with new links"""
    tmp_path, backend_url = storage
    FakeStorage.expired_once = True

    saver(tmp_path, backend_url, 100).saved()

    assert FakeStorage.renewals == 1 and saved_files() == {"dose.bdo": b"dose"}
