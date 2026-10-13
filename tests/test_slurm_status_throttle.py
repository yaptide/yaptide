"""GET /jobs/batch: SLURM queried over SSH at most once per interval and simulation, and the state it reports"""

from unittest.mock import MagicMock, Mock

from datetime import datetime, timedelta

import pytest
import requests
from sqlalchemy.exc import IntegrityError, OperationalError

from yaptide.application import create_app
from yaptide.batch import batch_methods
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    ClusterModel,
    KeycloakUserModel,
    SimulationModel,
    SlurmStatusCheckModel,
)
from yaptide.routes import batch_routes
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


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
        (["CANCELLED by 116752"], ["CANCELLED by 116752"], "CANCELED"),  # a cancel request is removing the jobs
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
        db.session.remove()  # an open transaction would block dropping the tables on Postgres
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
        """Another request stores COMPLETED while this one waits for SSH - its loaded simulation is now stale"""
        db.session.query(SimulationModel).filter_by(id=simulation.id).update(
            {"job_state": EntityState.COMPLETED.value}, synchronize_session=False
        )
        return {"job_state": EntityState.MERGING_RUNNING.value}

    monkeypatch.setattr(batch_routes, "get_job_status", collect_finishes_during_the_query)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: True)
    assert job_state(client) == (200, "COMPLETED")
    assert db.session.get(BatchSimulationModel, batch_simulation.id).job_state == "COMPLETED"


def test_cancelled_simulation_answered_from_database(client, batch_simulation, monkeypatch):
    """A cancelled simulation is final - SLURM is not asked about it any more"""
    batch_simulation.job_state = EntityState.CANCELED.value
    db.session.commit()
    get_job_status = Mock()
    monkeypatch.setattr(batch_routes, "get_job_status", get_job_status)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: True)
    assert job_state(client) == (200, "CANCELED")
    get_job_status.assert_not_called()


def test_submit_error_marks_the_simulation_failed(monkeypatch):
    """An unexpected error before the jobs are queued reports FAILED instead of leaving the simulation pending"""
    posted = []
    monkeypatch.setattr(batch_methods, "post_update", posted.append)
    monkeypatch.setattr(batch_methods, "_submit_job", Mock(side_effect=OSError("connection lost")))
    batch_methods.submit_job({}, {}, 1, 1, sim_id=5, update_key="key")
    assert [update["job_state"] for update in posted] == ["FAILED"]


def test_submit_closes_its_database_and_ssh_connections(monkeypatch):
    """The submitter process lives long - each submit closes what it opened, also when the cluster is unreachable"""
    db_con, engine = Mock(), Mock()
    monkeypatch.setattr(batch_methods, "connect_to_db", lambda: (db_con, Mock(), engine))
    monkeypatch.setattr(batch_methods, "get_user", lambda **_: Mock(cert="cert", private_key="key"))
    monkeypatch.setattr(batch_methods, "get_cluster", lambda **_: Mock())
    ssh = MagicMock()
    ssh.__enter__.return_value = ssh
    ssh.run.side_effect = OSError("login node unreachable")
    monkeypatch.setattr(batch_methods, "get_connection", lambda user, cluster: ssh)
    posted = []
    monkeypatch.setattr(batch_methods, "post_update", posted.append)
    batch_methods.submit_job({}, {}, 1, 1, sim_id=5, update_key="key")
    db_con.close.assert_called_once()
    engine.dispose.assert_called_once()
    ssh.__exit__.assert_called_once()
    assert [update["job_state"] for update in posted] == ["FAILED"]


def test_job_ids_report_failure_does_not_mark_queued_jobs_failed(monkeypatch):
    """Once sbatch queued the jobs, reporting their ids is retried and never turns into a FAILED simulation"""
    posted = []

    def report(update):
        """The backend got the ids, but the answer never arrived"""
        posted.append(update)
        raise requests.ConnectionError("connection reset")

    monkeypatch.setattr(batch_methods, "post_update", report)
    monkeypatch.setattr(batch_methods.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(batch_methods, "_submit_job", Mock(return_value={"sim_id": 5, "array_id": 11}))
    with pytest.raises(requests.ConnectionError):
        batch_methods.submit_job({}, {}, 1, 1, sim_id=5, update_key="key")
    assert posted == [{"sim_id": 5, "array_id": 11}] * batch_methods.JOB_IDS_REPORT_ATTEMPTS


def test_simulation_deleted_during_the_slurm_query(client, batch_simulation, monkeypatch):
    """The user may delete the simulation while its SLURM state is being read - the answer is 404, not a crash"""

    def delete_during_the_query(simulation, user, cluster):
        """Another request deletes the simulation while this one waits for SSH"""
        db.session.query(SimulationModel).filter_by(id=simulation.id).delete(synchronize_session=False)
        db.session.commit()
        return {"job_state": EntityState.RUNNING.value}

    monkeypatch.setattr(batch_routes, "get_job_status", delete_during_the_query)
    monkeypatch.setattr(batch_routes, "slurm_status_due", lambda sim_id: True)
    assert job_state(client)[0] == 404


def test_cancel_does_not_undo_results_stored_meanwhile(client, batch_simulation, monkeypatch):
    """A results upload that completes the simulation while the cancel runs its SSH calls is kept"""

    def results_arrive_during_the_cancel(simulation, user, cluster):
        """Another request stores COMPLETED while this one cancels the SLURM jobs"""
        db.session.query(SimulationModel).filter_by(id=simulation.id).update(
            {"job_state": EntityState.COMPLETED.value}, synchronize_session=False
        )
        return {"message": "Job canceled"}, 200

    monkeypatch.setattr(batch_routes, "delete_job", results_arrive_during_the_cancel)
    assert job_state(client, "delete")[0] == 200
    assert db.session.get(BatchSimulationModel, batch_simulation.id).job_state == "COMPLETED"


@pytest.fixture
def throttle(monkeypatch):
    """Throttle of GET /jobs/batch in a server process that has not asked SLURM about anything yet"""
    monkeypatch.setattr(batch_routes, "_last_local_check", {})
    return batch_routes


def test_slurm_status_checked_once_per_interval_by_all_processes(client, batch_simulation, throttle):
    """The first caller of an interval gets the SLURM query; another server process does not, until it passes"""
    sim_id = batch_simulation.id
    assert throttle.slurm_status_due(sim_id)
    assert not throttle.slurm_status_due(sim_id)
    # what another server process sees: its own cache and its own session - only a committed claim is shared
    throttle._last_local_check.clear()
    db.session.remove()
    assert not throttle.slurm_status_due(sim_id)
    db.session.query(SlurmStatusCheckModel).update(
        {"checked_at": datetime.utcnow() - timedelta(seconds=throttle.SLURM_STATUS_INTERVAL + 1)}
    )
    db.session.commit()
    assert throttle.slurm_status_due(sim_id)
    throttle._last_local_check.clear()
    assert not throttle.slurm_status_due(sim_id)
    assert db.session.query(SlurmStatusCheckModel).count() == 1


def test_slurm_status_checked_per_simulation(client, batch_simulation, throttle):
    """Each simulation has its own interval"""
    other = BatchSimulationModel(
        job_id="otherjob",
        user_id=batch_simulation.user_id,
        cluster_id=batch_simulation.cluster_id,
        input_type=InputType.EDITOR.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="other",
    )
    db.session.add(other)
    db.session.commit()
    assert throttle.slurm_status_due(batch_simulation.id)
    assert throttle.slurm_status_due(other.id)


def test_slurm_status_of_a_deleted_simulation_is_not_due(client, batch_simulation, throttle, monkeypatch):
    """A simulation deleted meanwhile violates the foreign key of its claim (on Postgres) - SLURM is not asked"""
    violation = IntegrityError("INSERT", {}, Exception("violates foreign key constraint"))
    monkeypatch.setattr(throttle, "claim_slurm_status_check", Mock(side_effect=violation))
    assert not throttle.slurm_status_due(batch_simulation.id)


def test_database_error_falls_back_to_the_per_process_throttle(client, batch_simulation, throttle, monkeypatch):
    """When the check cannot be recorded, SLURM is still asked, but once per interval in each server process"""
    monkeypatch.setattr(
        throttle, "claim_slurm_status_check", Mock(side_effect=OperationalError("UPDATE", {}, Exception("locked")))
    )
    assert throttle.slurm_status_due(batch_simulation.id)
    assert not throttle.slurm_status_due(batch_simulation.id)
    assert job_state(client) == (200, "MERGING_QUEUED")


@pytest.fixture
def batch_user(client) -> KeycloakUserModel:
    """Logged in Keycloak user with a certificate, and one cluster to submit to"""
    user = KeycloakUserModel(username="plgfrodo", cert="cert", private_key="key")
    db.session.add_all([user, ClusterModel(cluster_name="ares")])
    db.session.commit()
    client.set_cookie("access_token", encode_auth_token(user.id, is_keycloak=True)[0], domain="127.0.0.1")
    return user


def test_submit_hands_the_stored_simulation_to_ray(client, batch_user, monkeypatch, payload_files_dict_data: dict):
    """The submitter gets the job only once the simulation, its tasks and input are stored as PENDING"""
    seen = {}

    def submitter_gets(**submit_kwargs):
        """Records what the submitter would find in the database at the hand-off"""
        simulation = db.session.get(BatchSimulationModel, submit_kwargs["sim_id"])
        seen.update(
            submit_kwargs, state=simulation.job_state, tasks=len(simulation.tasks), inputs=len(simulation.inputs)
        )

    monkeypatch.setattr(batch_routes, "submit_batch_job", submitter_gets)
    response = client.post("/jobs/batch", json=payload_files_dict_data)
    assert response.status_code == 202
    assert seen["state"] == "PENDING"
    assert seen["tasks"] == payload_files_dict_data["ntasks"]
    assert seen["inputs"] == 1
    assert seen["userId"] == batch_user.id
    assert seen["files_dict"].keys() == payload_files_dict_data["input_files"].keys()


def test_submit_without_ray_fails_the_simulation(client, batch_user, monkeypatch, payload_files_dict_data: dict):
    """When the Ray cluster cannot be reached the user gets 503 and the simulation is not left pending"""
    monkeypatch.setattr(batch_routes, "submit_batch_job", Mock(side_effect=ConnectionError("ray client timeout")))
    response = client.post("/jobs/batch", json=payload_files_dict_data)
    assert response.status_code == 503
    assert BatchSimulationModel.query.one().job_state == EntityState.FAILED.value


def test_simulation_deleted_while_the_throttle_commits(client, batch_simulation, throttle, monkeypatch):
    """The throttle commits, so the simulation is read again - deleted meanwhile, the answer is 404, not a crash"""

    def deleted_meanwhile(sim_id, interval_seconds):
        """Another request deletes the simulation just before this one commits its claim"""
        db.session.query(SimulationModel).filter_by(id=sim_id).delete(synchronize_session=False)
        db.session.commit()
        return False

    monkeypatch.setattr(throttle, "claim_slurm_status_check", deleted_meanwhile)
    assert job_state(client)[0] == 404
