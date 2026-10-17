"""Partial results: stored in place of the previous ones while a simulation runs, replaced by the final ones"""

import copy
import io
import json
import shutil
import struct
import tarfile
import threading
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from flask import current_app

from yaptide.application import create_app
from yaptide.batch import watcher
from yaptide.engine import simulation as simulation_module
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    CelerySimulationModel,
    EstimatorModel,
    PageModel,
    SimulationModel,
    YaptideUserModel,
)
from yaptide.routes import events_routes
from yaptide.routes.common_sim_routes import store_partial_results, store_results
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.utils.sim_utils import merge_simulation_outputs, set_shieldhit_save_step

BDO_DIR = Path(__file__).parent / "res" / "bdo"
RESULTS = json.loads((Path(__file__).parent / "res" / "json_with_results.json").read_text())["estimators"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client of a logged in user with a running simulation, on a database file the stream's thread shares"""
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'yaptide.db'}")
    app = create_app()
    with app.app_context():
        db.create_all()
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
        simulation = CelerySimulationModel(
            job_id="partialjob",
            user_id=user.id,
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            title="partial",
            job_state=EntityState.RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        client = app.test_client()
        client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
        yield client
        db.session.remove()
        db.drop_all()


def simulation() -> CelerySimulationModel:
    """The simulation as stored"""
    db.session.remove()
    return db.session.query(CelerySimulationModel).filter_by(job_id="partialjob").one()


def first_page_data(client) -> list:
    """Data of the first page of the first estimator, as the UI reads it"""
    content = client.get(
        "/results", query_string={"job_id": "partialjob", "estimator_name": RESULTS[0]["name"]}
    ).get_json()
    return content["pages"][0]["data"]["values"]


def scaled(factor: float) -> list[dict]:
    """The results with the first page's values multiplied, to tell partial and final results apart"""
    estimators = copy.deepcopy(RESULTS)
    page = estimators[0]["pages"][0]
    page["data"]["values"] = [value * factor for value in page["data"]["values"]]
    return estimators


def test_partial_results_are_replaced_by_the_next_and_by_the_final_ones(client):
    """The UI reads partial results like final ones; the status says what they cover"""
    assert store_partial_results(simulation(), scaled(2), 300)
    assert first_page_data(client) == scaled(2)[0]["pages"][0]["data"]["values"]
    pages = db.session.query(PageModel).count()

    assert store_partial_results(simulation(), scaled(3), 600)
    assert first_page_data(client) == scaled(3)[0]["pages"][0]["data"]["values"]
    assert db.session.query(PageModel).count() == pages
    status = client.get("/jobs", query_string={"job_id": "partialjob", "tasks": False}).get_json()
    assert status["partial_results"]["simulated_primaries"] == 600
    assert status["partial_results"]["time"].endswith("+00:00")

    store_results(simulation(), RESULTS)
    assert first_page_data(client) == RESULTS[0]["pages"][0]["data"]["values"]
    assert simulation().job_state == EntityState.COMPLETED.value


@pytest.mark.parametrize("job_state", [EntityState.MERGING_QUEUED.value, EntityState.COMPLETED.value])
def test_partial_results_of_a_simulation_no_longer_running_are_dropped(client, job_state):
    """Partial results merged while the final ones were on their way never replace them"""
    stored = simulation()
    stored.job_state = job_state
    db.session.commit()

    assert not store_partial_results(simulation(), RESULTS, 300)
    assert db.session.query(PageModel).count() == 0
    assert simulation().partial_primaries is None


@pytest.mark.parametrize(
    "beam, expected",
    [
        ("NSTAT       10000    0       ! NSTAT, Step of saving\n", "NSTAT       10000    100       ! NSTAT, Step"),
        ("NSTAT 100\nTMAX0 10.0\n", "NSTAT 100    100\nTMAX0"),
        ("NSTAT 100 5000 ! own step\n", "NSTAT 100 5000 ! own step"),
    ],
)
def test_shieldhit_saves_every_tenth_of_a_task_unless_the_input_says_otherwise(beam, expected):
    """The step of saving is the second number of NSTAT; 0 or none means a save only at the end"""
    files = {"beam.dat": beam}
    set_shieldhit_save_step(files, 1000)
    assert files["beam.dat"].startswith(expected)


def read_event(lines) -> dict:
    """Next event of a stream, skipping keepalive comments"""
    for line in lines:
        if line.startswith(b"data: "):
            return json.loads(line[len(b"data: ") :])
    raise AssertionError("stream ended")


def running_simulation(user_id: int, job_id: str) -> None:
    """Another simulation of a user, as submitted"""
    db.session.add(
        CelerySimulationModel(
            job_id=job_id,
            user_id=user_id,
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            title=job_id,
            job_state=EntityState.PENDING.value,
        )
    )
    db.session.commit()


def test_stream_sends_the_status_of_the_users_simulations_when_they_change(client, monkeypatch):
    """Woken by the database (here every 2 s, SQLite has no notifications); a final state is sent once, simulations
    submitted while the stream is open join it
    """
    monkeypatch.setattr(events_routes, "subscribers", events_routes.Subscribers())
    user_id = simulation().user_id
    running_simulation(user_id, "finishedjob")
    db.session.query(SimulationModel).filter_by(job_id="finishedjob").update({"job_state": "COMPLETED"})
    db.session.commit()
    response = client.get("/events/simulations", buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    lines = response.iter_encoded()
    lines = (line for chunk in lines for line in chunk.splitlines())

    first = read_event(lines)
    assert (first["job_id"], first["job_state"]) == ("partialjob", EntityState.RUNNING.value)
    store_partial_results(simulation(), RESULTS, 300)
    assert read_event(lines)["partial_results"]["simulated_primaries"] == 300

    app = current_app._get_current_object()

    def finish() -> None:
        """The final results stored by the engine, while the stream waits"""
        with app.app_context():
            store_results(simulation(), RESULTS)

    finished = threading.Timer(0.5, finish)
    finished.start()
    assert read_event(lines)["job_state"] == EntityState.COMPLETED.value
    finished.join()

    running_simulation(user_id, "nextjob")
    assert read_event(lines)["job_id"] == "nextjob"
    response.close()


def test_stream_has_only_the_users_simulations(client):
    """Others' simulations are not on it, nor the user's finished before it opened"""
    other = YaptideUserModel(username="Saruman")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    running_simulation(other.id, "otherjob")
    user_id = simulation().user_id
    running_simulation(user_id, "finishedjob")
    db.session.query(SimulationModel).filter_by(job_id="finishedjob").update({"job_state": "COMPLETED"})
    db.session.commit()

    sent = events_routes.statuses(user_id, None, [])

    assert [content["job_id"] for _, content in sent] == ["partialjob"]
    client.delete_cookie("access_token", domain="127.0.0.1")
    assert client.get("/events/simulations").status_code == 401


def test_final_results_are_no_longer_partial(client):
    """The status of a completed simulation does not describe partial results any more"""
    assert store_partial_results(simulation(), scaled(2), 300)
    store_results(simulation(), RESULTS)
    status = client.get("/jobs", query_string={"job_id": "partialjob", "tasks": False}).get_json()
    assert "partial_results" not in status


def test_final_results_replace_partial_ones_named_otherwise(client):
    """The cluster's convertmc names the estimators of input files with a trailing underscore, the merge on the
    server without: the final results leave none of the partial ones behind
    """
    partial = [{**estimator, "name": estimator["name"].rstrip("_")} for estimator in scaled(2)]
    assert store_partial_results(simulation(), partial, 300)
    store_results(simulation(), RESULTS)

    names = {estimator.file_name for estimator in db.session.query(EstimatorModel)}
    assert names == {estimator["name"] for estimator in RESULTS} and names != {e["name"] for e in partial}
    assert db.session.query(PageModel).count() == sum(len(estimator["pages"]) for estimator in RESULTS)


def test_files_from_windows_get_a_step_of_saving():
    """Line ends of beam.dat written on Windows"""
    files = {"beam.dat": "NSTAT 1000 0\r\nTMAX0 10.0\r\n"}
    set_shieldhit_save_step(files, 1000)
    assert files["beam.dat"].startswith("NSTAT 1000    100\r\n")


def test_merge_of_missing_task_outputs_fails(tmp_path, monkeypatch):
    """A merge without some tasks' outputs would be stored as the whole result"""
    with pytest.raises(FileNotFoundError):
        merge_simulation_outputs([BDO_DIR / "task_1", tmp_path / "gone"])

    monkeypatch.setenv("TMPDIR", str(tmp_path))
    # nor in a bucket, if one is configured: simulation ids start at 1
    with pytest.raises((FileNotFoundError, ClientError)):
        simulation_module.merge_stored([result_storage.work_key(0, 1)])


def test_results_passed_through_storage_merge_as_from_the_task_directories(tmp_path, monkeypatch):
    """The archive a task stores keeps its result files as they were"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    keys = []
    for task in ("task_1", "task_2"):
        work_dir = shutil.copytree(BDO_DIR / task, tmp_path / task)
        keys.append(result_storage.work_key(1, int(task[-1])))
        result_storage.put_file(keys[-1], simulation_module.pack_results(work_dir))
        assert not (work_dir / "results.tar.gz").exists()

    assert simulation_module.merge_stored(keys) == merge_simulation_outputs([BDO_DIR / "task_1", BDO_DIR / "task_2"])

    result_storage.delete_objects(result_storage.work_prefix(1))
    assert not list(tmp_path.rglob("*.tar.gz"))


def test_saves_from_the_cluster_merge_as_from_the_task_directories(tmp_path, monkeypatch):
    """An HPC task's save, packed by its watcher, goes through the same merge as the saves of direct tasks"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    keys = []
    for task in ("task_1", "task_2"):
        keys.append(result_storage.work_key(1, int(task[-1])))
        archive = tmp_path / f"{task}.tar.gz"
        assert watcher.pack(BDO_DIR / task, archive)
        result_storage.put_file(keys[-1], archive)

    assert simulation_module.merge_stored(keys) == merge_simulation_outputs([BDO_DIR / "task_1", BDO_DIR / "task_2"])


def archive_with(tmp_path: Path, name: str, size: int = 4, kind: bytes = tarfile.REGTYPE) -> Path:
    """An archive with one member, as a job on the cluster could put it into storage"""
    archive = tmp_path / "bad.tar.gz"
    member = tarfile.TarInfo(name)
    member.type, member.size = kind, size if kind == tarfile.REGTYPE else 0
    if kind == tarfile.SYMTYPE:
        member.linkname = "/etc/passwd"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(member, io.BytesIO(b"x" * member.size))
    return archive


@pytest.mark.parametrize(
    "name, size, kind",
    [
        ("notes.txt", 4, tarfile.REGTYPE),
        ("../dose.bdo", 4, tarfile.REGTYPE),
        ("nested/dose.bdo", 4, tarfile.REGTYPE),
        ("dose.bdo", 0, tarfile.SYMTYPE),
        ("dose.bdo", 2000, tarfile.REGTYPE),
    ],
    ids=["other file", "outside", "nested", "link", "too large"],
)
def test_saves_with_anything_but_result_files_are_not_merged(tmp_path, monkeypatch, name, size, kind):
    """A save comes from the cluster: other files, links, paths or more data than allowed fail the merge"""
    monkeypatch.setenv("TMPDIR", str(tmp_path / "objects"))
    key = result_storage.work_key(1, 1)
    result_storage.put_file(key, archive_with(tmp_path, name, size, kind))

    with pytest.raises(ValueError):
        simulation_module.merge_stored([key], max_bytes=1000)
    assert not [path for path in tmp_path.rglob("*") if path.is_file() and path.suffix != ".gz"]


def crafted_bdo(offset: int, value: int) -> bytes:
    """A result file of the test data with one number changed, as a job on the cluster could write it"""
    data = bytearray((BDO_DIR / "task_1" / "z_profile_0001.bdo").read_bytes())
    data[offset : offset + 8] = struct.pack("<q", value)
    return bytes(data)


@pytest.mark.parametrize(
    "files, error",
    [
        # the items of the first page declared as 2**36 numbers: its reader would take 512 GB of memory
        ({"z_profile_0001.bdo": crafted_bdo(1808 + 16, 1 << 36)}, "larger than the file"),
        # 10**9 bins along z with 10 values: the JSON would hold a value for every bin
        ({"z_profile_0001.bdo": crafted_bdo(1240 + 16, 10**9)}, "values for"),
        ({"fluence_fort.21": b"x"}, "not a result file"),
        ({f"{number}.bdo": b"" for number in range(simulation_module.MAX_RESULT_FILES + 1)}, "too much"),
    ],
    ids=["entry larger than the file", "more bins than values", "FLUKA file", "too many files"],
)
def test_crafted_saves_are_not_merged(tmp_path, monkeypatch, files, error):
    """A few bytes from the cluster must not take the server's memory or time"""
    monkeypatch.setenv("TMPDIR", str(tmp_path / "objects"))
    archive = tmp_path / "save.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    key = result_storage.work_key(1, 1)
    result_storage.put_file(key, archive)

    with pytest.raises(ValueError, match=error):
        simulation_module.merge_stored([key], max_bytes=1 << 20)


def test_save_rewritten_while_packed_is_not_stored(tmp_path, monkeypatch):
    """The simulator's next save may start while the last one is packed; a torn archive is not merged"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    work_dir = tmp_path / "task"
    work_dir.mkdir()
    (work_dir / "dose.bdo").write_bytes(b"save 1")
    add = tarfile.TarFile.add

    def add_during_next_save(self, name, *args, **kwargs):
        """Packs a file, while the simulator writes its next save"""
        add(self, name, *args, **kwargs)
        Path(name).write_bytes(b"save 2, longer")

    key = result_storage.work_key(1, 1)
    saved = []
    monkeypatch.setattr(tarfile.TarFile, "add", add_during_next_save)
    simulation_module.store_save(work_dir, key, 100, lambda key, primaries: saved.append((key, primaries)))
    assert not saved
    assert not list(tmp_path.rglob("*.tar.gz"))

    monkeypatch.setattr(tarfile.TarFile, "add", add)
    simulation_module.store_save(work_dir, key, 200, lambda key, primaries: saved.append((key, primaries)))
    assert saved == [(key, 200)]
    result_storage.get_file(key, tmp_path / "save.tar.gz")
    with tarfile.open(tmp_path / "save.tar.gz") as tar:
        assert tar.extractfile("dose.bdo").read() == b"save 2, longer"


def test_one_user_cannot_take_every_stream(monkeypatch):
    """Each stream holds a thread of the events server"""
    monkeypatch.setattr(events_routes, "subscribers", events_routes.Subscribers())
    for _ in range(events_routes.MAX_STREAMS_PER_USER):
        assert events_routes.subscribers.admit(7)
    assert not events_routes.subscribers.admit(7)
    assert events_routes.subscribers.admit(8)
    events_routes.subscribers.release(7)
    assert events_routes.subscribers.admit(7)
