"""HPC simulations: Flask only stores and flags them, the engine submits and cancels them over SSH"""

import json
import shlex
import subprocess
import time
from datetime import datetime, timezone
from unittest import mock

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    SSHCertificateBuilder,
    SSHCertificateType,
)
from fabric import Result
from paramiko import AuthenticationException, SSHException

from yaptide.application import create_app
from yaptide.batch import batch_methods
from yaptide.batch.fluka_string_templates import ARRAY_FLUKA_BASH, COLLECT_FLUKA_BASH
from yaptide.batch.shieldhit_string_templates import ARRAY_SHIELDHIT_BASH, COLLECT_SHIELDHIT_BASH, SUBMIT_SHIELDHIT
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    BatchTaskModel,
    ClusterModel,
    KeycloakUserModel,
    LogfilesModel,
    SimulationModel,
)
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.routes.utils.utils import update_state_from_tasks
from yaptide.utils.enums import EntityState

SUBMIT_OUTPUT = "Job id: 101\nAggregator id: 102\nCollect id: 103\nReporter id: 104\n"


@pytest.fixture
def client(monkeypatch):
    """Test client of a logged in Keycloak user with a certificate, and one cluster"""
    monkeypatch.setenv("YAPTIDE_TOKEN_SECRET", "shared with the backend")
    monkeypatch.setenv("BACKEND_EXTERNAL_URL", "https://yaptide.test")
    # the jobs report through the results storage, links to it are signed at submit
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(
        batch_methods.result_storage,
        "job_links",
        lambda sim_id, saving_tasks=0: {
            "progress": {"url": "https://s3.test", "fields": {}, "prefix": f"{sim_id}/"},
            "cancel": "x",
            "saves": {"urls": {str(task): f"https://s3.test/{task}" for task in range(1, saving_tasks + 1)}},
        },
    )
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


def test_refused_connection_fails_the_simulation(client, monkeypatch):
    """An SSH error that waiting would not fix ends the submit with FAILED instead of a simulation pending forever"""
    simulation_id = submit(client).id

    def refused(**_):
        """The cluster refuses the login"""
        raise AuthenticationException("certificate refused")

    monkeypatch.setattr(batch_methods, "get_connection", refused)
    assert batch_methods.submit_simulation(simulation_id) is None

    assert stored(simulation_id).job_state == EntityState.FAILED.value


def test_login_node_not_answering_leaves_the_simulation_waiting(client, monkeypatch):
    """A login node that does not answer in time is tried again later: the simulation stays PENDING"""
    simulation_id = submit(client).id

    def unreachable(**_):
        """The login node does not answer"""
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(batch_methods, "get_connection", unreachable)
    assert batch_methods.submit_simulation(simulation_id) is False

    assert stored(simulation_id).job_state == EntityState.PENDING.value
    assert stored(simulation_id).job_dir is None


def frozen_login_node() -> Exception:
    """What paramiko raises when the login node accepts the connection but never sends its banner"""
    try:
        try:
            raise TimeoutError()
        except TimeoutError:
            raise SSHException("Error reading SSH protocol banner")
    except SSHException as error:
        return error


@pytest.mark.parametrize(
    "error, stuck",
    [
        (TimeoutError("connection timed out"), True),
        (frozen_login_node(), True),
        (RuntimeError("slurm_load_jobs error: Socket timed out on send/recv operation"), True),
        (RuntimeError("sbatch: error: Unable to contact slurm controller (connect failure)"), True),
        (AuthenticationException("timed out certificate"), False),
        (EOFError("connection closed"), False),
        (RuntimeError("sbatch: error: invalid account"), False),
    ],
)
def test_only_a_cluster_not_answering_in_time_counts_as_stuck(error, stuck):
    """Waiting helps a SLURM or login node that does not answer in time, not a refused login or bad input"""
    assert batch_methods.slurm_stuck(error) is stuck


def test_stuck_slurm_leaves_the_simulation_waiting_and_its_jobs_are_cancelled_before_the_next_submit(
    client, cluster_connection, monkeypatch
):
    """sbatch timing out may still leave jobs in SLURM: the simulation stays PENDING with the attempt's directory,
    and the next submit (once the attempt surely ended) first cancels its jobs by id and name, then submits anew
    """
    simulation_id = submit(client).id
    run = cluster_connection.run.side_effect
    stuck = Result(
        stdout="Job id: \n",
        stderr="sbatch: error: Batch job submission failed: Socket timed out on send/recv operation",
        command="sh",
        exited=0,
        connection=None,
    )
    cluster_connection.run.side_effect = lambda command, **kwargs: (
        stuck if command.startswith("sh ") else run(command, **kwargs)
    )

    assert batch_methods.submit_simulation(simulation_id) is False
    first_dir = stored(simulation_id).job_dir
    assert stored(simulation_id).job_state == EntityState.PENDING.value and first_dir
    assert not any("scancel" in command for command in commands(cluster_connection))

    cluster_connection.run.reset_mock()
    cluster_connection.run.side_effect = run
    # the script of the attempt may still run on the login node
    assert batch_methods.submit_simulation(simulation_id) is None
    cluster_connection.run.assert_not_called()

    monkeypatch.setattr(batch_methods, "SUBMIT_SECONDS", 0)
    assert batch_methods.submit_simulation(simulation_id) is True
    sent = commands(cluster_connection)
    assert f"--name={batch_methods.job_name(first_dir)}" in sent[0]
    assert sum(command.startswith("sh ") for command in sent) == 1
    simulation = stored(simulation_id)
    assert simulation.job_dir != first_dir and (simulation.array_id, simulation.collect_id) == (101, 103)


def test_cancel_only_flags_and_the_engine_cancels_the_jobs(client, cluster_connection):
    """DELETE /jobs/batch stores CANCELED; the engine's cancel stops every job by id and removes the directory"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    cluster_connection.run.reset_mock()

    assert client.delete("/jobs/batch", query_string={"job_id": simulation.job_id}).status_code == 200
    cluster_connection.run.assert_not_called()
    assert stored(simulation.id).job_state == EntityState.CANCELED.value

    job_dir = stored(simulation.id).job_dir
    assert batch_methods.cancel_simulation(simulation.id) is True
    (sent,) = commands(cluster_connection)  # one round trip, bounded on the login node
    timeout, seconds, shell, flag, script = shlex.split(sent)
    assert (timeout, int(seconds), shell, flag) == ("timeout", batch_methods.CANCEL_SECONDS, "sh", "-c")
    # every job by the id the submit wrote next to it, the reporter first; then by the submit's name, the directory
    cancelled = [part.split("/")[-1].split("_job_id")[0] for part in script.split("; ")[:-1]]
    assert cancelled == ["reporter", "collect", "array", "aggregator"]  # the aggregator of jobs submitted before
    name = batch_methods.job_name(job_dir)
    assert script.split("; ")[-1] == f"scancel --name={name} --user=$USER && rm -rf {job_dir}"
    assert stored(simulation.id).job_dir is None  # nothing left to cancel


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

    cancels = [command for command in commands(cluster_connection) if "scancel" in command]
    assert len(cancels) == 1 and cancels[0].count("scancel") == len(batch_methods.SIMULATION_JOBS) + 1
    assert stored(simulation.id).job_state == EntityState.CANCELED.value


def test_status_is_read_from_the_database_only(client, cluster_connection):
    """GET /jobs/batch never connects to the cluster"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    cluster_connection.run.reset_mock()

    response = client.get("/jobs/batch", query_string={"job_id": simulation.job_id, "tasks": "false"})

    assert response.get_json()["job_state"] == EntityState.PENDING.value
    cluster_connection.run.assert_not_called()


def test_status_says_when_a_busy_cluster_is_tried_again(client, cluster_connection):
    """A simulation waiting for a cluster whose SLURM does not answer says when it is tried again; once submitted,
    its jobs wait in SLURM and the cluster's state is not its own any more
    """
    simulation = submit(client)
    db.session.get(ClusterModel, simulation.cluster_id).busy_until = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    db.session.commit()

    response = client.get("/jobs/batch", query_string={"job_id": simulation.job_id, "tasks": "false"})
    assert response.get_json()["cluster_busy_until"] == "2026-10-18T12:00:00+00:00"

    batch_methods.submit_simulation(simulation.id)
    response = client.get("/jobs/batch", query_string={"job_id": simulation.job_id, "tasks": "false"})
    assert "cluster_busy_until" not in response.get_json()


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


def test_job_dir_from_a_job_never_reaches_a_command(client, cluster_connection):
    """A job may only say it merges or failed; a job directory or a cancel from it is refused"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    key = encode_simulation_auth_token(simulation.id)

    for update in ({"job_dir": "~; touch /tmp/pwned"}, {"job_state": "CANCELED"}, {"array_id": 1}):
        response = client.post("/jobs", json={"sim_id": simulation.id, "update_key": key, **update})
        assert response.status_code == 400
    assert stored(simulation.id).job_dir.startswith("/scratch/plgtest/yaptide_runs/")
    assert (
        client.post(
            "/jobs", json={"sim_id": simulation.id, "update_key": key, "job_state": "MERGING_RUNNING"}
        ).status_code
        == 202
    )


def test_unexpected_job_dir_is_never_used_in_a_command(client, cluster_connection):
    """Even a job directory that got into the database some other way is not put into a command"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    db.session.execute(
        BatchSimulationModel.__table__.update()
        .where(BatchSimulationModel.__table__.c.id == simulation.id)
        .values(job_dir="/scratch/x; rm -rf ~")
    )
    db.session.commit()
    cluster_connection.run.reset_mock()

    batch_methods.cancel_simulation(simulation.id)

    cluster_connection.run.assert_not_called()


def test_cancel_before_the_claim_submits_nothing(client, cluster_connection):
    """A simulation cancelled while the submit connects is not submitted"""
    simulation = submit(client)
    run = cluster_connection.run.side_effect

    def cancel_while_connecting(command: str, **kwargs) -> Result:
        """The user cancels while the submit asks for $SCRATCH"""
        if command == "echo $SCRATCH":
            with db.engine.begin() as other:
                other.execute(
                    SimulationModel.__table__.update()
                    .where(SimulationModel.__table__.c.id == simulation.id)
                    .values(job_state=EntityState.CANCELED.value)
                )
        return run(command, **kwargs)

    cluster_connection.run.side_effect = cancel_while_connecting
    batch_methods.submit_simulation(simulation.id)

    assert not any(command.startswith("sh ") for command in commands(cluster_connection))


def test_delete_waits_for_the_cancel_on_the_cluster(client, cluster_connection):
    """Deleting a cancelled simulation before its jobs are cancelled would leave them running"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)
    client.delete("/jobs/batch", query_string={"job_id": simulation.job_id})

    assert client.delete("/user/simulations", query_string={"job_id": simulation.job_id}).status_code == 409
    batch_methods.cancel_simulation(simulation.id)
    assert client.delete("/user/simulations", query_string={"job_id": simulation.job_id}).status_code == 200


def test_delete_waits_for_the_cleanup_of_a_failed_submit(client, cluster_connection):
    """A submit failing half way may have left jobs on the cluster, cancelled by the engine before a delete"""
    simulation = submit(client)
    run = cluster_connection.run.side_effect

    def drop_after_the_claim(command: str, **kwargs) -> Result:
        """The login node drops the connection once the job directory is recorded, also the cancel's"""
        if command == "echo $SCRATCH":
            return run(command, **kwargs)
        raise EOFError("the login node closed the connection")

    cluster_connection.run.side_effect = drop_after_the_claim
    batch_methods.submit_simulation(simulation.id)
    assert db.session.get(BatchSimulationModel, simulation.id).job_state == EntityState.FAILED.value

    assert client.delete("/user/simulations", query_string={"job_id": simulation.job_id}).status_code == 409


def test_jobs_get_new_links_while_running(client, cluster_connection, monkeypatch):
    """A job running past the links' week gets new ones with its update key; not once the simulation is final"""
    simulation = submit(client)
    key = encode_simulation_auth_token(simulation.id)

    response = client.post("/tasks/links", json={"simulation_id": simulation.id, "update_key": key})
    assert response.status_code == 200
    assert response.get_json()["links"]["cancel"] == "x"
    wrong = encode_simulation_auth_token(simulation.id + 1)
    assert client.post("/tasks/links", json={"simulation_id": simulation.id, "update_key": wrong}).status_code == 400

    client.delete("/jobs/batch", query_string={"job_id": simulation.job_id})
    assert client.post("/tasks/links", json={"simulation_id": simulation.id, "update_key": key}).status_code == 409


def test_submit_puts_the_links_and_scripts_next_to_the_jobs(client, cluster_connection):
    """storage_links.json and the scripts are put as files; the array script hands the simulator's pid to the
    watcher, and there is no aggregator any more
    """
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)

    put = {call.args[1].rsplit("/", 1)[-1]: call.args[0] for call in cluster_connection.put.call_args_list}
    assert {"storage_links.json", "array_script.sh", "collect_script.sh", "yaptide_submitter.sh"} <= set(put)
    array_script = put["array_script.sh"].getvalue().decode()
    assert "SIMULATOR_PID=$!" in array_script and "--pid=$SIMULATOR_PID" in array_script
    # the watcher runs as long as the simulation, its command line is visible to others on the node
    update_key = json.loads(put["storage_links.json"].getvalue())["update_key"]
    assert update_key and update_key not in array_script and "--update_key" not in ARRAY_FLUKA_BASH
    submit_script = put["yaptide_submitter.sh"].getvalue().decode()
    assert "aggregator" not in submit_script and "pyzmq" not in submit_script
    for script in ("array_script.sh", "collect_script.sh", "yaptide_submitter.sh"):
        checked = subprocess.run(
            ["bash", "-n"], input=put[script].getvalue().decode(), capture_output=True, text=True, check=False
        )
        assert checked.returncode == 0, checked.stderr


def test_shieldhit_tasks_on_the_cluster_save_along_the_way(client, cluster_connection, monkeypatch):
    """The cluster's copy of the input saves every tenth of a task, and each task gets a link for its saves; the
    stored input stays the user's
    """
    uploaded = {}
    monkeypatch.setattr(batch_methods, "upload_inputs", lambda con, job_dir, files: uploaded.update(files))
    simulation = submit(client, ntasks=2)
    batch_methods.submit_simulation(simulation.id)

    assert uploaded["beam.dat"].startswith("NSTAT 50    5\n")
    put = {call.args[1].rsplit("/", 1)[-1]: call.args[0] for call in cluster_connection.put.call_args_list}
    assert set(json.loads(put["storage_links.json"].getvalue())["saves"]["urls"]) == {"1", "2"}
    assert stored(simulation.id).inputs[0].data["input_files"]["beam.dat"] == "NSTAT 50 0\n"


def test_uploads_to_the_cluster_have_a_timeout(client, cluster_connection):
    """A hung login node does not hold the engine's connection forever while files are put"""
    simulation = submit(client)
    batch_methods.submit_simulation(simulation.id)

    calls = [str(call) for call in cluster_connection.mock_calls]
    timeout = calls.index(f"call.sftp().get_channel().settimeout({batch_methods.COMMAND_SECONDS})")
    assert timeout < min(index for index, call in enumerate(calls) if call.startswith("call.put("))


def test_failed_submit_cancels_what_reached_the_cluster(client, cluster_connection):
    """sbatch failing half way may leave the array queued: it is cancelled and the directory removed"""
    simulation_id = submit(client).id
    run = cluster_connection.run.side_effect
    cluster_connection.run.side_effect = lambda command, **kwargs: (
        Result(
            stdout="Job id: 101\n", stderr="sbatch: error: collect refused", command=command, exited=1, connection=None
        )
        if command.startswith("sh ")
        else run(command, **kwargs)
    )

    batch_methods.submit_simulation(simulation_id)

    assert stored(simulation_id).job_state == EntityState.FAILED.value
    assert any("scancel" in command for command in commands(cluster_connection))
    assert stored(simulation_id).job_dir is None


def ssh_certificate(valid_before: int) -> tuple[str, str]:
    """A private key and an SSH certificate for it, signed by a throwaway CA"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = ed25519.Ed25519PrivateKey.generate()
    certificate = (
        SSHCertificateBuilder()
        .public_key(key.public_key())
        .type(SSHCertificateType.USER)
        .valid_principals([b"plgtest"])
        .valid_after(0)
        .valid_before(valid_before)
        .sign(ca)
    )
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()
    return pem, certificate.public_bytes().decode()


def test_no_login_with_an_expired_certificate():
    """A login bound to fail is not tried: failed logins count against the account on the cluster"""
    cluster = ClusterModel(cluster_name="ares")
    pem, expired = ssh_certificate(int(time.time()) - 60)
    with pytest.raises(AuthenticationException, match="expired"):
        batch_methods.get_connection(KeycloakUserModel(username="plgtest", cert=expired, private_key=pem), cluster)

    pem, valid = ssh_certificate(int(time.time()) + 3600)
    connection = batch_methods.get_connection(
        KeycloakUserModel(username="plgtest", cert=valid, private_key=pem), cluster
    )
    assert connection.user == "plgtest" and not connection.is_connected  # nothing connects before a command


def stub_commands(bin_dir, **scripts: str) -> dict:
    """Executables standing in for the cluster's commands, each a line of bash; the environment to run with them"""
    bin_dir.mkdir()
    for name, body in scripts.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin"}


def render(template: str, root_dir) -> str:
    """A job script as the submit writes it"""
    return template.format(
        array_header="",
        collect_header="",
        root_dir=root_dir,
        n_tasks=3,
        sim_id=1,
        update_key="key",
        backend_url="https://yaptide.test",
        remove_output_from_workspace="true",
    )


@pytest.mark.parametrize("array_template", [ARRAY_SHIELDHIT_BASH, ARRAY_FLUKA_BASH], ids=["shieldhit", "fluka"])
def test_the_last_array_task_collects_once(tmp_path, array_template):
    """Three tasks ending at once: exactly one of them runs the collect script, as the last of them"""
    for attempt in range(5):
        root = tmp_path / str(attempt)
        for task in (1, 2, 3):
            (root / "workspaces" / f"task_{task:04d}").mkdir(parents=True)
        (root / "input").mkdir()
        (root / "input" / "x.inp").write_text("")
        (root / "done").mkdir()
        (root / "array_script.sh").write_text(render(array_template, root))
        # the collect looks at the done markers: all three are there when it runs
        (root / "collect_script.sh").write_text(f"echo $1 `ls {root}/done | wc -l` >> {root}/collects; sleep 0.3\n")
        env = stub_commands(root / "bin", srun="sleep 0.2", python3="true", module="true")
        tasks = [
            subprocess.Popen(
                ["bash", str(root / "array_script.sh")],
                env={**env, "SLURM_ARRAY_TASK_ID": str(task)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for task in (1, 2, 3)
        ]
        assert [task.wait() for task in tasks] == [0, 0, 0]
        assert (root / "collects").read_text().split() == ["inline", "3"]
        assert (root / "collect.lock").is_dir()


@pytest.mark.parametrize("collect_template", [COLLECT_SHIELDHIT_BASH, COLLECT_FLUKA_BASH], ids=["shieldhit", "fluka"])
def test_the_collect_job_collects_only_what_the_last_task_did_not(tmp_path, collect_template):
    """A failed inline collect reports nothing final and keeps the task outputs; the collect job then tries
    again (whatever the lock) and reports the failure; after a successful one it just ends
    """
    (tmp_path / "workspaces" / "task_0001").mkdir(parents=True)
    task_output = tmp_path / "workspaces" / "task_0001" / "a.bdo_fort.1"
    task_output.write_text("")
    script = tmp_path / "collect_script.sh"
    script.write_text(render(collect_template, tmp_path).replace("*.bdo", "*.bdo_fort.1"))
    (tmp_path / "collect.lock").mkdir()  # left by the task that tried
    reports = tmp_path / "reports"
    env = stub_commands(
        tmp_path / "bin",
        python3=f'echo "$@" >> {reports}',
        module="true",
        convertmc='[ -f "$HOME/merges" ] && touch out.json',
    )

    def collect(*args) -> int:
        """Runs the collect script; its exit code"""
        return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, check=False).returncode

    env["HOME"] = str(tmp_path)  # convertmc fails until the file $HOME/merges exists
    assert collect("inline") == 1
    assert "FAILED" not in reports.read_text() and task_output.exists()
    assert collect() == 1
    assert "--simulation_state=FAILED" in reports.read_text()

    (tmp_path / "merges").write_text("")
    reports.unlink()
    assert collect("inline") == 0
    # inline the array task holds its node: a few upload attempts, the collect job has more
    assert "--attempts=3" in reports.read_text()
    (tmp_path / "collected").unlink()
    task_output.write_text("")
    reports.unlink()
    assert collect() == 0
    assert "--attempts=12" in reports.read_text()
    assert "results_uploader.py" in reports.read_text() and (tmp_path / "collected").exists()
    assert not task_output.exists()  # removed only after the upload
    reports.unlink()
    assert collect() == 0
    assert not reports.exists()  # collected already: no report at all


@pytest.mark.parametrize("stuck", [False, True], ids=["answers", "stuck"])
def test_the_submit_script_names_every_job_and_gives_a_stuck_sbatch_up(tmp_path, stuck):
    """All three jobs carry the submit's name; an sbatch the timeout ended says so, and nothing after it is
    submitted
    """
    (tmp_path / "input.zip").write_text("")
    script = tmp_path / "yaptide_submitter.sh"
    script.write_text(
        SUBMIT_SHIELDHIT.format(
            root_dir=tmp_path,
            n_tasks=2,
            array_options="--account=grant",
            collect_options="",
            reporter_options="--job-name=yaptide_1_2",
            convertmc_version="1",
            job_name="yaptide_1_2",
            sbatch_seconds=5,
            sim_id=1,
            update_key="key",
            backend_url="https://yaptide.test",
        )
    )
    calls = tmp_path / "sbatch_calls"
    env = stub_commands(
        tmp_path / "bin",
        module="true",
        unzip="true",
        sbatch=f'echo "$@" >> {calls}; echo 7',
        # the real one runs the command, or ends it after the given seconds with 124
        timeout="exit 124" if stuck else 'shift; exec "$@"',
    )

    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, check=False)

    if stuck:
        assert "sbatch timed out after 5 s" in done.stderr and batch_methods.SLURM_STUCK.search(done.stderr)
        assert "Job id: \n" in done.stdout and "Collect id" not in done.stdout
        assert not calls.exists()
    else:
        assert done.stdout.splitlines() == ["Job id: 7", "Collect id: 7", "Reporter id: 7"]
        names = [line.count("--job-name=yaptide_1_2") for line in calls.read_text().splitlines()]
        assert names == [1, 1, 1]


@pytest.mark.parametrize("slurm_answers", [True, False], ids=["answers", "stuck"])
def test_the_cancel_command_cancels_by_name_and_keeps_the_directory_while_slurm_is_stuck(tmp_path, slurm_answers):
    """The jobs go by their ids, then by the submit's name (a job whose id was never written); the directory goes
    only once SLURM answered
    """
    job_dir = tmp_path / "scratch" / "yaptide_runs" / "5_1700000000000000"
    job_dir.mkdir(parents=True)
    (job_dir / "array_job_id").write_text("11\n")
    (job_dir / "collect_job_id").write_text("")  # sbatch given up: no id
    calls = tmp_path / "scancel_calls"
    env = stub_commands(
        tmp_path / "bin",
        scancel=f'echo "$@" >> {calls}' + ("" if slurm_answers else "; echo Socket timed out >&2; exit 1"),
        timeout='shift; exec "$@"',
    )

    done = subprocess.run(
        batch_methods.cancel_command(str(job_dir)),
        shell=True,
        env={**env, "USER": "plgtest"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert calls.read_text().splitlines() == ["11", "--name=yaptide_5_1700000000000000 --user=plgtest"]
    assert (done.returncode == 0) == slurm_answers
    assert job_dir.exists() != slurm_answers
