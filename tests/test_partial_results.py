"""Partial results: stored in place of the previous ones while a simulation runs, replaced by the final ones"""

import copy
import json
import threading
from pathlib import Path

import pytest
from flask import current_app

from yaptide.application import create_app
from yaptide.engine import simulation as simulation_module
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, PageModel, YaptideUserModel
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
    return db.session.query(CelerySimulationModel).one()


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


def test_stream_sends_the_status_when_it_changes_and_ends_with_the_simulation(client, monkeypatch):
    """Woken by the database (here every 2 s, SQLite has no notifications); a finished simulation ends the stream"""
    monkeypatch.setattr(events_routes, "subscribers", events_routes.Subscribers())
    response = client.get("/events/simulation", query_string={"job_id": "partialjob"}, buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    lines = response.iter_encoded()
    lines = (line for chunk in lines for line in chunk.splitlines())

    assert read_event(lines)["job_state"] == EntityState.RUNNING.value
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
    assert [line for line in lines if line] == []
    finished.join()


def test_stream_of_someone_elses_simulation_is_refused(client):
    """Only the owner follows a simulation"""
    other = YaptideUserModel(username="Saruman")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    client.set_cookie("access_token", encode_auth_token(other.id)[0], domain="127.0.0.1")

    assert client.get("/events/simulation", query_string={"job_id": "partialjob"}).status_code == 403


def test_final_results_are_no_longer_partial(client):
    """The status of a completed simulation does not describe partial results any more"""
    assert store_partial_results(simulation(), scaled(2), 300)
    store_results(simulation(), RESULTS)
    status = client.get("/jobs", query_string={"job_id": "partialjob", "tasks": False}).get_json()
    assert "partial_results" not in status


def test_files_from_windows_get_a_step_of_saving():
    """Line ends of beam.dat written on Windows"""
    files = {"beam.dat": "NSTAT 1000 0\r\nTMAX0 10.0\r\n"}
    set_shieldhit_save_step(files, 1000)
    assert files["beam.dat"].startswith("NSTAT 1000    100\r\n")


def test_merge_of_missing_task_outputs_fails(tmp_path):
    """A merge without some tasks' outputs would be stored as the whole result"""
    with pytest.raises(FileNotFoundError):
        merge_simulation_outputs([BDO_DIR / "task_1", tmp_path / "gone"])


def test_snapshot_rewritten_while_copied_is_dropped(tmp_path, monkeypatch):
    """The simulator's next save may start while the last one is copied; a torn copy is not merged"""
    (tmp_path / "dose.bdo").write_bytes(b"save 1")
    copy_file = simulation_module.shutil.copy

    def copy_during_next_save(source, target):
        """Copies, while the simulator writes its next save"""
        copy_file(source, target)
        Path(source).write_bytes(b"save 2, longer")

    monkeypatch.setattr(simulation_module.shutil, "copy", copy_during_next_save)
    saved = []
    simulation_module.take_snapshot(tmp_path, 100, lambda path, primaries: saved.append(path))
    assert not saved
    assert not list(tmp_path.glob("snapshot_*"))

    monkeypatch.setattr(simulation_module.shutil, "copy", copy_file)
    simulation_module.take_snapshot(tmp_path, 200, lambda path, primaries: saved.append(path))
    assert saved == [str(tmp_path / "snapshot_000000000200")]


def test_one_user_cannot_take_every_stream(monkeypatch):
    """Each stream holds a thread of the events server"""
    monkeypatch.setattr(events_routes, "subscribers", events_routes.Subscribers())
    for _ in range(events_routes.MAX_STREAMS_PER_USER):
        assert events_routes.subscribers.admit(7)
    assert not events_routes.subscribers.admit(7)
    assert events_routes.subscribers.admit(8)
    events_routes.subscribers.release(7)
    assert events_routes.subscribers.admit(7)
