"""HPC simulations: Flask only stores and flags them, the engine submits and cancels them over SSH"""

from unittest import mock

import pytest
from fabric import Result

from yaptide.application import create_app
from yaptide.batch import batch_methods
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    BatchTaskModel,
    ClusterModel,
    KeycloakUserModel,
    LogfilesModel,
    SimulationModel,
)
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.routes.utils.utils import update_state_from_tasks
from yaptide.utils.enums import EntityState

SUBMIT_OUTPUT = "Job id: 101\nAggregator id: 102\nCollect id: 103\nReporter id: 104\n"


@pytest.fixture
def client(monkeypatch):
    """Test client of a logged in Keycloak user with a certificate, and one cluster"""
    monkeypatch.setenv("YAPTIDE_TOKEN_SECRET", "shared with the backend")
    app = create_app()
    with app.app_context():
        db.create_all()
        user = KeycloakUserModel(username="plgtest", cert="cert", private_key="key")
        db.session.add_all([user, ClusterModel(cluster_name="ares")])
        db.session.commit()
        client = app.test_client()
        client.set_cookie("access_token", encode_auth_token(user.id, is_keycloak=True)[0], domain="127.0.0.1")
        yield client
        db.session.remove()
        db.drop_all()


def submit(client, ntasks: int = 2) -> BatchSimulationModel:
    """Stores an HPC simulation through the API, as the UI does"""
    payload = {
        "input_type": "files",
        "sim_type": "shieldhit",
        "ntasks": ntasks,
        "input_files": {"beam.dat": "NSTAT 100 0\n", "geo.dat": "", "mat.dat": "", "detect.dat": ""},
        "batch_options": {"array_options": {"account": "grant"}},
    }
    response = client.post("/jobs/batch", json=payload)
    assert response.status_code == 202
    return db.session.query(BatchSimulationModel).filter_by(job_id=response.get_json()["job_id"]).one()


@pytest.fixture
def cluster_connection(monkeypatch) -> mock.MagicMock:
    """SSH connection to the cluster: every command succeeds, sbatch reports the job ids"""
    connection = mock.MagicMock()
    connection.__enter__.return_value = connection

    def run(command: str, **_) -> Result:
        """What the login node answers"""
        stdout = "/scratch/plgtest\n" if command == "echo $SCRATCH" else ""
        if command.startswith("sh ") and command.endswith("yaptide_submitter.sh"):
            stdout = SUBMIT_OUTPUT
        return Result(stdout=stdout, stderr="", command=command, exited=0, connection=None)

    connection.run.side_effect = run
    monkeypatch.setattr(batch_methods, "get_connection", lambda **_: connection)
    return connection


def commands(connection: mock.MagicMock) -> list[str]:
    """Commands run on the login node, in order"""
    return [call.args[0] for call in connection.run.call_args_list]


def stored(simulation_id: int) -> BatchSimulationModel:
    """The simulation as stored, read in a fresh session"""
    db.session.remove()
    return db.session.get(BatchSimulationModel, simulation_id)


def test_submit_stores_everything_and_leaves_the_cluster_to_the_engine(client, cluster_connection):
    """One commit with the simulation PENDING, its tasks and input (with the sbatch options); no SSH from Flask"""
    simulation = submit(client, ntasks=3)

    assert simulation.job_state == EntityState.PENDING.value
    assert [task.task_id for task in db.session.query(BatchTaskModel).order_by(BatchTaskModel.task_id)] == [1, 2, 3]
    assert simulation.inputs[0].data["batch_options"] == {"array_options": {"account": "grant"}}
    cluster_connection.run.assert_not_called()


def test_engine_submits_with_the_job_dir_recorded_first(client, cluster_connection):
    """The job directory is in the database before sbatch runs; the job ids are stored after it"""
    simulation_id = submit(client).id
    job_dirs_at_sbatch = []
    run = cluster_connection.run.side_effect

    def record_job_dir(command: str, **kwargs) -> Result:
        """Notes what the database holds when sbatch is called"""
        if command.startswith("sh "):
            job_dirs_at_sbatch.append(stored(simulation_id).job_dir)
        return run(command, **kwargs)

    cluster_connection.run.side_effect = record_job_dir
    batch_methods.submit_simulation(simulation_id)

    simulation = stored(simulation_id)
    assert simulation.job_dir.startswith(f"/scratch/plgtest/yaptide_runs/{simulation_id}_")
    assert job_dirs_at_sbatch == [simulation.job_dir]
    assert (simulation.array_id, simulation.collect_id) == (101, 103)
    assert simulation.job_state == EntityState.PENDING.value


def test_a_simulation_is_submitted_once(client, cluster_connection):
    """A second submit of the same simulation (a sweep, another engine) does nothing"""
    simulation_id = submit(client).id
    batch_methods.submit_simulation(simulation_id)
    batch_methods.submit_simulation(simulation_id)

    assert sum(command.startswith("sh ") for command in commands(cluster_connection)) == 1


def test_failed_sbatch_fails_the_simulation_with_its_output(client, cluster_connection):
    """No job ids: FAILED, with what sbatch said for the user to see"""
    simulation_id = submit(client).id
    run = cluster_connection.run.side_effect
    cluster_connection.run.side_effect = lambda command, **kwargs: (
        Result(stdout="", stderr="sbatch: error: invalid account", command=command, exited=1, connection=None)
        if command.startswith("sh ")
        else run(command, **kwargs)
    )

    batch_methods.submit_simulation(simulation_id)

    assert stored(simulation_id).job_state == EntityState.FAILED.value
    log = db.session.query(LogfilesModel).filter_by(simulation_id=simulation_id).one().data
    assert log["submit_stderr"] == "sbatch: error: invalid account"


def test_unreachable_cluster_fails_the_simulation(client, monkeypatch):
    """An SSH error ends the submit with FAILED instead of a simulation pending forever"""
    simulation_id = submit(client).id

    def unreachable(**_):
        """The login node does not answer"""
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(batch_methods, "get_connection", unreachable)
    batch_methods.submit_simulation(simulation_id)

    assert stored(simulation_id).job_state == EntityState.FAILED.value


def test_cancel_only_flags_and_the_engine_cancels_the_jobs(client, cluster_connection):
    """DELETE /jobs/batch stores CANCELED; the engine's cancel stops every job by id and removes the directory"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    cluster_connection.run.reset_mock()

    assert client.delete("/jobs/batch", query_string={"job_id": simulation.job_id}).status_code == 200
    cluster_connection.run.assert_not_called()
    assert stored(simulation.id).job_state == EntityState.CANCELED.value

    batch_methods.cancel_simulation(simulation.id)
    sent = commands(cluster_connection)
    assert sent[:2] == ["scancel 103", "scancel 101"]
    assert any("reporter_job_id" in command for command in sent)
    assert sent[-1].startswith("rm -rf /scratch/plgtest/yaptide_runs/")


def test_cancel_during_submit_cancels_the_jobs_right_after(client, cluster_connection):
    """A cancel stored while sbatch runs finds no job ids; the submit then cancels what it just submitted"""
    simulation = submit(client)
    run = cluster_connection.run.side_effect

    def cancel_meanwhile(command: str, **kwargs) -> Result:
        """The user cancels while the submit script runs"""
        if command.startswith("sh "):
            with db.engine.begin() as other:
                other.execute(
                    SimulationModel.__table__.update()
                    .where(SimulationModel.__table__.c.id == simulation.id)
                    .values(job_state=EntityState.CANCELED.value)
                )
        return run(command, **kwargs)

    cluster_connection.run.side_effect = cancel_meanwhile
    batch_methods.submit_simulation(simulation.id)

    assert "scancel 103" in commands(cluster_connection)
    assert stored(simulation.id).job_state == EntityState.CANCELED.value


def test_status_is_read_from_the_database_only(client, cluster_connection):
    """GET /jobs/batch never connects to the cluster"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    cluster_connection.run.reset_mock()

    response = client.get("/jobs/batch", query_string={"job_id": simulation.job_id, "tasks": "false"})

    assert response.get_json()["job_state"] == EntityState.PENDING.value
    cluster_connection.run.assert_not_called()


@pytest.mark.parametrize(
    "task_states, before, expected",
    [
        (["RUNNING", "PENDING"], "PENDING", "RUNNING"),
        (["COMPLETED", "FAILED"], "RUNNING", "MERGING_QUEUED"),
        (["COMPLETED", "COMPLETED"], "MERGING_RUNNING", "MERGING_RUNNING"),  # never back
        (["FAILED", "FAILED"], "RUNNING", "FAILED"),
        (["COMPLETED", "COMPLETED"], "CANCELED", "CANCELED"),
    ],
)
def test_hpc_state_follows_task_reports(client, task_states, before, expected):
    """Without asking SLURM: the tasks' reports move the simulation, the collect job reports the rest"""
    simulation = submit(client)
    for task, task_state in zip(simulation.tasks, task_states):
        task.task_state = task_state
    simulation.job_state = before
    db.session.commit()

    update_state_from_tasks(simulation)

    assert stored(simulation.id).job_state == expected
