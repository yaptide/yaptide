import pytest
from sqlalchemy.exc import DataError, OperationalError
from yaptide.application import create_app
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel, YaptideUserModel
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
