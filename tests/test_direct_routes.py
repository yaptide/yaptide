"""/jobs/direct when the Ray cluster misbehaves, and the backend client when the backend is down"""

from datetime import datetime, timedelta, timezone

import pytest

from yaptide.application import create_app
from yaptide.direct import backend_client
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel, YaptideUserModel
from yaptide.routes import direct_routes
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


@pytest.fixture
def app():
    """Flask app with an empty database, recreated for every test"""
    _app = create_app()
    with _app.app_context():
        db.create_all()
        yield _app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def user(app) -> YaptideUserModel:
    """A logged-in local user"""
    user = YaptideUserModel(username="Frodo")
    user.set_password("ring")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client(app, user):
    """Test client sending the user's access token"""
    client = app.test_client()
    client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
    return client


@pytest.fixture
def running_simulation(user) -> CelerySimulationModel:
    """A direct simulation with two running tasks"""
    simulation = CelerySimulationModel(
        job_id="directjob",
        user_id=user.id,
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="direct",
        job_state=EntityState.RUNNING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    for task_id in (0, 1):
        db.session.add(
            CeleryTaskModel(
                simulation_id=simulation.id,
                task_id=task_id,
                requested_primaries=100,
                task_state=EntityState.RUNNING.value,
            )
        )
    db.session.commit()
    return simulation


def test_submit_without_ray_fails_the_simulation(client, monkeypatch, payload_files_dict_data: dict):
    """When the Ray cluster cannot be reached the user gets 503 and the simulation is not left pending"""

    def unreachable(**_):
        """Fails like a Ray client that cannot connect"""
        raise ConnectionError("ray client connection timeout")

    monkeypatch.setattr(direct_routes, "submit_simulation", unreachable)

    response = client.post("/jobs/direct", json=payload_files_dict_data)

    assert response.status_code == 503
    assert CelerySimulationModel.query.one().job_state == EntityState.FAILED.value


def test_cancel_marks_canceled_even_when_ray_fails(client, running_simulation, monkeypatch):
    """A failing cancel on the Ray side still lets the user cancel the simulation"""

    def broken_cancel(**_):
        """Fails like a Ray head that cannot be reached"""
        raise ConnectionError("ray client connection timeout")

    monkeypatch.setattr(direct_routes, "cancel_simulation", broken_cancel)

    response = client.delete("/jobs/direct?job_id=directjob")

    assert response.status_code == 200
    db.session.refresh(running_simulation)
    assert running_simulation.job_state == EntityState.CANCELED.value


def test_simulation_without_reports_is_marked_failed(client, running_simulation):
    """A running simulation whose tasks stopped reporting long ago is marked failed when the UI asks for it"""
    old = datetime.now(timezone.utc) - timedelta(seconds=direct_routes.ABANDONED_TASKS_SECONDS + 60)
    for task in CeleryTaskModel.query.all():
        task.last_update_time = old
    db.session.commit()

    response = client.get("/jobs/direct?job_id=directjob")

    assert response.get_json()["job_state"] == EntityState.FAILED.value
    assert {task.task_state for task in CeleryTaskModel.query.all()} == {EntityState.FAILED.value}


def test_simulation_with_recent_reports_keeps_running(client, running_simulation):
    """A simulation reporting within the limit is left alone"""
    response = client.get("/jobs/direct?job_id=directjob")

    assert response.get_json()["job_state"] == EntityState.RUNNING.value


def test_backend_client_survives_backend_outage(monkeypatch):
    """A backend that cannot be reached is reported as False after the retries, never as an exception"""
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(backend_client, "FINAL_POST_RETRY_SECONDS", 0)

    assert not backend_client.send_task_updates(1, "key", {0: {"task_state": "RUNNING"}})
    assert not backend_client.send_job_state(1, "key", {"job_state": "FAILED"}, attempts=3)
    assert not backend_client.send_simulation_results(1, "key", [])
