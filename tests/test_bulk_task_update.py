import pytest
from sqlalchemy.exc import DataError, OperationalError
from yaptide.application import create_app
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import bulk_update_task_states, update_reported_tasks
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel, TaskModel, YaptideUserModel
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


@pytest.fixture
def app():
    """Flask app with an empty database, recreated for every test"""
    _app = create_app()
    with _app.app_context():
        db.create_all()
        yield _app
        db.drop_all()


@pytest.fixture
def simulation_with_tasks(app) -> CelerySimulationModel:
    """Simulation with two pending tasks, as created right after job submission"""
    user = YaptideUserModel(username="Gandalf")
    user.set_password("Mellon")
    db.session.add(user)
    db.session.commit()

    simulation = CelerySimulationModel(
        job_id="bulkjob",
        user_id=user.id,
        input_type=InputType.EDITOR.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="bulktitle",
    )
    db.session.add(simulation)
    db.session.commit()

    for task_id in (1, 2):
        db.session.add(CeleryTaskModel(simulation_id=simulation.id, task_id=task_id, requested_primaries=1000))
    db.session.commit()
    return simulation


def test_bulk_update_updates_all_tasks(app, simulation_with_tasks: CelerySimulationModel):
    """Single request updates every task listed in the payload"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"task_state": EntityState.RUNNING.value, "simulated_primaries": 500}},
            {"task_id": 2, "update_dict": {"task_state": EntityState.RUNNING.value, "simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    tasks = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id).order_by(CeleryTaskModel.task_id)
    simulated_primaries = [task.simulated_primaries for task in tasks]
    assert simulated_primaries == [500, 600]
    assert all(task.task_state == EntityState.RUNNING.value for task in tasks)


def test_bulk_update_skips_invalid_task_update_and_keeps_the_rest(app, simulation_with_tasks: CelerySimulationModel):
    """One malformed update must not fail the batch, the aggregator would retry the whole batch forever"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"end_time": "not a date"}},
            {"task_id": 2, "update_dict": {"simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=2).first()
    assert task.simulated_primaries == 600


def test_bulk_update_rejects_invalid_update_key(app, simulation_with_tasks: CelerySimulationModel):
    """Updates signed for another simulation are refused"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id + 1),
        "tasks": [{"task_id": 1, "update_dict": {"simulated_primaries": 500}}],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 400
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=1).first()
    assert task.simulated_primaries == 0


def test_bulk_update_keeps_other_tasks_when_the_database_rejects_a_value(
    app, simulation_with_tasks: CelerySimulationModel
):
    """A value only the database refuses fails the commit - the other tasks still land and the request succeeds"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"requested_primaries": 2**70}},
            {"task_id": 2, "update_dict": {"simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    tasks = {task.task_id: task for task in CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id)}
    assert tasks[1].requested_primaries == 1000
    assert tasks[2].simulated_primaries == 600


def test_bulk_update_skips_a_malformed_update_as_a_whole(app, simulation_with_tasks: CelerySimulationModel):
    """Fields set before the malformed one must not be saved - the task would end COMPLETED without end_time"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [{"task_id": 1, "update_dict": {"task_state": EntityState.COMPLETED.value, "end_time": "not a date"}}],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=1).first()
    assert task.task_state == EntityState.PENDING.value
    assert task.end_time is None


def test_bulk_update_rejects_payload_that_is_not_an_object(app):
    """A JSON list is not a bulk update"""
    resp = app.test_client().post("/tasks/bulk", json=[1, 2])
    assert resp.status_code == 400


def test_bulk_update_fails_when_the_database_itself_fails(app, simulation_with_tasks, monkeypatch):
    """An unavailable database is not bad data - the request fails, so the aggregator retries the batch"""

    def failing_commit():
        """Database refusing every write"""
        raise OperationalError("COMMIT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(db.session, "commit", failing_commit)
    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [{"task_id": 1, "update_dict": {"simulated_primaries": 500}}],
    }
    # the test app propagates the exception, a deployed flask answers it with 500
    with pytest.raises(OperationalError):
        app.test_client().post("/tasks/bulk", json=payload)


def test_bulk_update_fails_when_the_database_fails_during_the_task_by_task_retry(
    app, simulation_with_tasks, monkeypatch
):
    """A database outage during the task-by-task retry is not bad data either - the request fails"""
    errors = [DataError("COMMIT", {}, Exception("out of range")), OperationalError("COMMIT", {}, Exception("gone"))]

    def failing_commit():
        """First commit rejects a value, the next one finds the database gone"""
        raise errors.pop(0)

    monkeypatch.setattr(db.session, "commit", failing_commit)
    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [{"task_id": 1, "update_dict": {"simulated_primaries": 500}}],
    }
    with pytest.raises(OperationalError):
        app.test_client().post("/tasks/bulk", json=payload)


def test_bulk_update_rejects_a_user_token_as_update_key(app, simulation_with_tasks):
    """A token without simulation_id is an invalid update key, not a server error"""
    from yaptide.routes.utils.tokens import encode_auth_token  # skipcq: PYL-C0415

    token, _ = encode_auth_token(user_id=1)
    payload = {"simulation_id": simulation_with_tasks.id, "update_key": token, "tasks": []}
    assert app.test_client().post("/tasks/bulk", json=payload).status_code == 400


@pytest.mark.parametrize("path", ["/tasks", "/tasks/links"])
@pytest.mark.parametrize("simulation_id", [[1], "1", True, {"id": 1}])
def test_task_routes_reject_a_simulation_id_that_is_not_an_integer(app, simulation_with_tasks, path, simulation_id):
    """A malformed simulation_id is a bad request, not a server error"""
    payload = {
        "simulation_id": simulation_id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
    }
    if path == "/tasks":
        payload.update(task_id=1, update_dict={"simulated_primaries": 5})
    assert app.test_client().post(path, json=payload).status_code == 400


REPORTED_STEPS = [
    {"simulated_primaries": 0, "estimated_time": 50},
    {"task_state": "RUNNING", "simulated_primaries": 300, "start_time": "2026-10-18 10:00:00.000001"},
    {"start_time": "2026-10-18 11:00:00.000001", "requested_primaries": 2000, "estimated_time": 0},
    {"requested_primaries": 0, "simulated_primaries": 500, "estimated_time": 40},
    {"end_time": "2026-10-18 12:00:00.000001", "estimated_time": 30},
    {"end_time": "2026-10-18 13:00:00.000001", "estimated_time": 20, "simulated_primaries": 900},
    {"task_state": "COMPLETED", "simulated_primaries": 1000},
    {"task_state": "RUNNING", "simulated_primaries": 5},
]


@pytest.mark.parametrize("final", [None, EntityState.FAILED.value, EntityState.CANCELED.value])
def test_reported_updates_match_update_state(app, simulation_with_tasks: CelerySimulationModel, final):
    """The one statement for checked reports changes a task as TaskModel.update_state does, step by step"""
    if final:
        db.session.query(TaskModel).update({"task_state": final})
        db.session.commit()
    fields = (
        "task_state",
        "requested_primaries",
        "simulated_primaries",
        "estimated_time",
        "start_time",
        "end_time",
    )
    for step in REPORTED_STEPS:
        bulk_update_task_states(simulation_with_tasks.id, [{"task_id": 1, "update_dict": step}])
        update_reported_tasks(simulation_with_tasks.id, [{"task_id": 2, "update_dict": step}])
        db.session.commit()
        db.session.expire_all()
        by_orm, by_statement = (
            CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=task_id).one()
            for task_id in (1, 2)
        )
        assert [getattr(by_statement, name) for name in fields] == [getattr(by_orm, name) for name in fields], step
    assert by_statement.task_state == (final or EntityState.COMPLETED.value)
