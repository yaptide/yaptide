"""Status polled by the UI: totals over the tasks, the task list only on request, and no writes on read"""

import pytest

from yaptide.application import create_app
from yaptide.persistence import db_methods
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    CelerySimulationModel,
    CeleryTaskModel,
    SimulationModel,
    TaskModel,
    UserActivityModel,
    YaptideUserModel,
)
from yaptide.routes.utils import utils
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.routes.utils.utils import update_state_from_tasks
from yaptide.utils.enums import EntityState, InputType, SimulationType


@pytest.fixture
def client():
    """Test client with an empty database, recreated for every test"""
    app = create_app()
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def simulation(client) -> CelerySimulationModel:
    """Direct simulation of a logged in user with three tasks: running, completed and pending"""
    user = YaptideUserModel(username="Gandalf")
    user.set_password("Mellon")
    db.session.add(user)
    db.session.commit()
    simulation = CelerySimulationModel(
        job_id="statusjob",
        user_id=user.id,
        input_type=InputType.EDITOR.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="status",
        job_state=EntityState.PENDING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    states = {1: (EntityState.RUNNING, 400), 2: (EntityState.COMPLETED, 1000), 3: (EntityState.PENDING, 0)}
    for task_id, (state, simulated) in states.items():
        db.session.add(
            CeleryTaskModel(
                simulation_id=simulation.id,
                task_id=task_id,
                requested_primaries=1000,
                simulated_primaries=simulated,
                task_state=state.value,
            )
        )
    db.session.commit()
    # the test client sends cookies only to the domain the app is served on (FLASK_SERVER_NAME in pytest.ini)
    client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
    return simulation


def stored_state(sim_id: int) -> str:
    """Job state as stored, read in a fresh session"""
    db.session.remove()
    return db.session.get(SimulationModel, sim_id).job_state


def reopen_completed_task(sim_id: int) -> None:
    """Puts the completed task back to RUNNING, as a final task state cannot be changed by a report"""
    db.session.query(TaskModel).filter_by(simulation_id=sim_id, task_id=2).update({"task_state": "RUNNING"})
    db.session.commit()


def post_task_update(client, sim_id: int, task_id: int, update: dict) -> None:
    """A task reporting its state, as the simulation worker does"""
    response = client.post(
        "/tasks",
        json={
            "simulation_id": sim_id,
            "task_id": task_id,
            "update_key": encode_simulation_auth_token(sim_id),
            "update_dict": update,
        },
    )
    assert response.status_code == 202


@pytest.mark.parametrize("url", ["/jobs/direct", "/jobs"])
def test_status_has_totals_and_the_task_list_only_when_asked(client, simulation, url):
    """The UI asks without the task list and gets the same totals it would compute from the list"""
    full = client.get(url, query_string={"job_id": "statusjob"}).get_json()
    short = client.get(url, query_string={"job_id": "statusjob", "tasks": "false"}).get_json()

    summary = {
        "ntasks": 3,
        "task_states": {"RUNNING": 1, "COMPLETED": 1, "PENDING": 1},
        "requested_primaries": 3000,
        "simulated_primaries": 1400,
    }
    assert full["job_tasks_summary"] == summary
    assert short["job_tasks_summary"] == summary
    assert "job_tasks_status" not in short
    assert [task["simulated_primaries"] for task in full["job_tasks_status"]] == [400, 1000, 0]


def test_polled_status_tells_that_the_user_follows_their_simulations(client, simulation, monkeypatch):
    """Written down at most every 30 s by each process; a failed write does not fail the status"""
    monkeypatch.setattr(db_methods, "_watching_written", {})
    user_id = simulation.user_id

    def seen_at():
        """When the user was last seen following their simulations"""
        db.session.remove()
        return db.session.get(UserActivityModel, user_id).seen_at

    assert client.get("/jobs", query_string={"job_id": "statusjob"}).status_code == 200
    first = seen_at()
    assert client.get("/jobs", query_string={"job_id": "statusjob"}).status_code == 200
    assert seen_at() == first
    monkeypatch.setattr(db_methods, "WATCHING_WRITE_SECONDS", 0)
    assert client.get("/jobs", query_string={"job_id": "statusjob"}).status_code == 200
    assert seen_at() > first

    UserActivityModel.__table__.drop(db.engine)
    assert client.get("/jobs", query_string={"job_id": "statusjob"}).status_code == 200


def test_status_read_does_not_change_the_state(client, simulation):
    """A running task does not make the simulation RUNNING when someone looks, only when the task reports"""
    response = client.get("/jobs/direct", query_string={"job_id": "statusjob"})

    assert response.get_json()["job_state"] == "PENDING"
    assert stored_state(simulation.id) == "PENDING"


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({1: "RUNNING"}, "RUNNING"),
        ({1: "FAILED", 2: "FAILED", 3: "FAILED"}, "FAILED"),
        ({1: "COMPLETED", 2: "COMPLETED", 3: "COMPLETED"}, "RUNNING"),  # the merge reports the next state itself
    ],
)
def test_direct_state_follows_task_reports(client, simulation, updates, expected):
    """The state the status read used to compute is now set when tasks report"""
    reopen_completed_task(simulation.id)
    for task_id, state in updates.items():
        post_task_update(client, simulation.id, task_id, {"task_state": state})

    assert stored_state(simulation.id) == expected


def test_task_reports_do_not_undo_a_final_state(client, simulation):
    """A late progress report after a cancel leaves the simulation canceled"""
    simulation.job_state = EntityState.CANCELED.value
    db.session.commit()

    post_task_update(client, simulation.id, 3, {"task_state": "RUNNING"})

    assert stored_state(simulation.id) == "CANCELED"


def test_bulk_task_reports_set_the_direct_state(client, simulation):
    """The bulk endpoint moves the state the same way as single reports"""
    reopen_completed_task(simulation.id)
    response = client.post(
        "/tasks/bulk",
        json={
            "simulation_id": simulation.id,
            "update_key": encode_simulation_auth_token(simulation.id),
            "tasks": [{"task_id": task_id, "update_dict": {"task_state": "FAILED"}} for task_id in (1, 2, 3)],
        },
    )

    assert response.status_code == 202
    assert stored_state(simulation.id) == "FAILED"


def test_progress_reports_skip_the_state_check(client, simulation, monkeypatch):
    """Most reports carry only progress; they do not pay for counting the task states, but wake the streams"""
    counted = []
    monkeypatch.setattr(utils, "state_update_from_tasks", counted.append)
    sim_id = simulation.id
    revision = simulation.progress_revision

    post_task_update(client, sim_id, 1, {"simulated_primaries": 500})
    post_task_update(client, sim_id, 1, {"task_state": "COMPLETED"})

    assert len(counted) == 1
    db.session.remove()
    assert db.session.get(SimulationModel, sim_id).progress_revision == revision + 2


def test_failed_from_task_reports_has_an_end_time(client, simulation):
    """The merge's own FAILED report comes too late to set the end time, so the derived FAILED sets it"""
    sim_id = simulation.id
    reopen_completed_task(sim_id)
    for task_id in (1, 2, 3):
        post_task_update(client, sim_id, task_id, {"task_state": "FAILED"})

    db.session.remove()
    stored = db.session.get(SimulationModel, sim_id)
    assert stored.job_state == "FAILED"
    assert stored.end_time is not None


def test_derived_state_does_not_overwrite_a_cancel_stored_meanwhile(client, simulation):
    """A report handled while the user cancels must not turn the canceled simulation back to running"""
    sim_id = simulation.id
    stale = db.session.get(CelerySimulationModel, sim_id)
    db.session.refresh(stale)
    db.session.expunge(stale)  # what the report's request read before the cancel committed: PENDING
    db.session.query(SimulationModel).filter_by(id=sim_id).update({"job_state": "CANCELED"})
    db.session.commit()

    update_state_from_tasks(stale)

    assert stored_state(sim_id) == "CANCELED"
