"""GET /jobs/batch: SLURM queried over SSH at most once per interval and simulation, and the state it reports"""

from unittest.mock import Mock

import pytest
import redis

from yaptide.application import create_app
from yaptide.batch import batch_methods
from yaptide.persistence.database import db
from yaptide.persistence.models import BatchSimulationModel, ClusterModel, KeycloakUserModel, SimulationModel
from yaptide.routes import batch_routes
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


@pytest.fixture
def throttle(monkeypatch):
    """Throttle of GET /jobs/batch with nothing remembered, the tests set its Redis client"""
    monkeypatch.setattr(batch_routes, "_last_local_check", {})
    monkeypatch.setattr(batch_routes, "_redis_down_until", 0.0)
    return batch_routes


def test_slurm_status_checked_once_per_interval(throttle, monkeypatch):
    """Redis lets the first caller of an interval through and answers None to the others"""
    client = Mock()
    client.set.side_effect = [True, None]
    monkeypatch.setattr(throttle, "_redis", client)
    assert throttle.slurm_status_due(7)
    assert not throttle.slurm_status_due(7)
    client.set.assert_called_with("slurm_status:7", 1, nx=True, ex=throttle.SLURM_STATUS_INTERVAL)


def test_slurm_status_checked_once_per_interval_without_redis(throttle, monkeypatch):
    """Without Redis every server process lets one caller per interval and simulation through"""
    monkeypatch.setattr(throttle, "_redis", None)
    assert throttle.slurm_status_due(7)
    assert not throttle.slurm_status_due(7)
    assert throttle.slurm_status_due(8)


def test_failing_redis_is_left_alone_for_an_interval(throttle, monkeypatch):
    """A Redis error falls back to the per-process throttle and Redis is not asked again for an interval"""
    client = Mock()
    client.set.side_effect = redis.TimeoutError("hangs")
    monkeypatch.setattr(throttle, "_redis", client)
    assert throttle.slurm_status_due(7)
    assert not throttle.slurm_status_due(7)
    assert throttle.slurm_status_due(8)
    assert client.set.call_count == 1


def fake_sacct(monkeypatch, array_states: list[str], collect_states: list[str]) -> None:
    """Makes the SSH connection answer `sacct -n -P -X -j <id>` with the given states, array job 1, collect job 2"""
    output = {"1": array_states, "2": collect_states}
    connection = Mock()
    connection.run.side_effect = lambda command, hide: Mock(
        stdout="".join(f"{s}\n" for s in output[command.split()[5]])
    )
    monkeypatch.setattr(batch_methods, "get_connection", lambda user, cluster: connection)


@pytest.mark.parametrize(
    "array_states, collect_states, expected",
    [
        ([], [], "PENDING"),  # not in the SLURM accounting yet, right after submitting
        (["PENDING"], ["PENDING"], "PENDING"),
        (["RUNNING", "RUNNING", "PENDING"], ["PENDING"], "RUNNING"),
        (["COMPLETED", "RUNNING", "COMPLETED"], ["PENDING"], "RUNNING"),  # the order of the lines does not matter
        (["COMPLETED", "TIMEOUT", "CANCELLED by 116752"], ["PENDING"], "MERGING_QUEUED"),
        (["COMPLETED", "COMPLETED"], ["RUNNING"], "MERGING_RUNNING"),
        (["COMPLETED", "COMPLETED"], ["COMPLETED"], "COMPLETED"),
        (["COMPLETED", "COMPLETED"], ["TIMEOUT"], "FAILED"),  # a collect job past its time limit never finishes
        (["COMPLETED", "COMPLETED"], ["OUT_OF_MEMORY"], "FAILED"),
    ],
)
def test_job_status_from_sacct(monkeypatch, array_states, collect_states, expected):
    """The simulation state follows from all array task states and the collect job, never from one line"""
    fake_sacct(monkeypatch, array_states, collect_states)
    simulation = Mock(array_id=1, collect_id=2)
    assert batch_methods.get_job_status(simulation=simulation, user=None, cluster=None)["job_state"] == expected


@pytest.fixture
def client():
    """Test client with an empty database, recreated for every test"""
    app = create_app()
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


@pytest.fixture
def batch_simulation(client) -> BatchSimulationModel:
    """Batch simulation of a logged in Keycloak user, submitted to SLURM and waiting for its results"""
    user = KeycloakUserModel(username="plgfrodo", cert="cert", private_key="key")
    cluster = ClusterModel(cluster_name="ares")
    db.session.add_all([user, cluster])
    db.session.commit()
    simulation = BatchSimulationModel(
        job_id="batchjob",
        user_id=user.id,
        cluster_id=cluster.id,
        input_type=InputType.EDITOR.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="batchtitle",
        job_state=EntityState.MERGING_QUEUED.value,
        array_id=1,
        collect_id=2,
    )
    db.session.add(simulation)
    db.session.commit()
    # the test client sends cookies only to the domain the app is served on (FLASK_SERVER_NAME in pytest.ini)
    client.set_cookie("access_token", encode_auth_token(user.id, is_keycloak=True)[0], domain="127.0.0.1")
    return simulation


def job_state(client, method: str = "get") -> tuple[int, str]:
    """Status code and job state of the batch simulation, as the UI gets them"""
    response = getattr(client, method)("/jobs/batch?job_id=batchjob")
    return response.status_code, response.get_json().get("job_state")


def test_job_state_from_database_before_the_job_ids_are_known(client, batch_simulation, monkeypatch):
    """Right after submitting there is no SLURM job to ask about - the stored state is answered, cancel waits"""
    batch_simulation.array_id = batch_simulation.collect_id = None
    batch_simulation.job_state = EntityState.PENDING.value
    db.session.commit()
    get_job_status = Mock()
    monkeypatch.setattr(batch_routes, "get_job_status", get_job_status)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: True)
    assert job_state(client) == (200, "PENDING")
    assert job_state(client, "delete")[0] == 409
    get_job_status.assert_not_called()


def test_job_state_from_database_between_slurm_queries(client, batch_simulation, monkeypatch):
    """Requests that do not get the SLURM slot of the interval answer the stored state"""
    get_job_status = Mock()
    monkeypatch.setattr(batch_routes, "get_job_status", get_job_status)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: False)
    assert job_state(client) == (200, "MERGING_QUEUED")
    get_job_status.assert_not_called()


def test_slow_slurm_query_does_not_undo_the_final_state(client, batch_simulation, monkeypatch):
    """While SLURM still shows the collect job running, its results upload completes the simulation"""

    def collect_finishes_during_the_query(simulation, user, cluster):
        # another request stores COMPLETED while this one waits for SSH - its loaded simulation is now stale
        db.session.query(SimulationModel).filter_by(id=simulation.id).update(
            {"job_state": EntityState.COMPLETED.value}, synchronize_session=False
        )
        return {"job_state": EntityState.MERGING_RUNNING.value}

    monkeypatch.setattr(batch_routes, "get_job_status", collect_finishes_during_the_query)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: True)
    assert job_state(client) == (200, "COMPLETED")
    assert db.session.get(BatchSimulationModel, batch_simulation.id).job_state == "COMPLETED"
