import io
import json
import logging
import os
import re
import shlex
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zipfile import ZipFile

import pymchelper
from cryptography.hazmat.primitives.serialization import SSHCertificate, load_ssh_public_identity
from fabric import Connection, Result
from invoke.exceptions import CommandTimedOut
from paramiko import AuthenticationException, RSAKey

from yaptide.batch.shieldhit_string_templates import (
    ARRAY_SHIELDHIT_BASH,
    COLLECT_SHIELDHIT_BASH,
    FIND_MERGE_PYTHON,
    PARTIAL_SHIELDHIT_BASH,
    SUBMIT_SHIELDHIT,
)
from yaptide.batch.fluka_string_templates import ARRAY_FLUKA_BASH, COLLECT_FLUKA_BASH, SUBMIT_FLUKA
from yaptide.batch.utils.utils import (
    convert_dict_to_sbatch_options,
    helper_job_sbatch_options,
    extract_sbatch_header,
)
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import add_object_to_db, update_simulation_state
from yaptide.persistence.models import (
    BatchSimulationModel,
    ClusterModel,
    KeycloakUserModel,
    LogfilesModel,
    SimulationModel,
    TaskModel,
)
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, SimulationType
from yaptide.utils.sim_utils import set_shieldhit_save_step, write_simulation_input_files

# a command on the login node that does not end in this time is given up (a hung login node must not hold one of
# the engine's few connections forever); the submit script waits for sbatch several times
COMMAND_SECONDS = 60
SUBMIT_SECONDS = 300
# one sbatch waiting on a stuck SLURM controller is given up on the login node itself, so the submit script ends before
# the backend stops waiting for it (three of them, well within SUBMIT_SECONDS)
SBATCH_SECONDS = 60
# the cancel command gives up on the login node before the backend stops waiting for it
CANCEL_SECONDS = COMMAND_SECONDS - 10
# what paramiko says when the server closes the connection while logging in, e.g. after accepting the key
LOGIN_CLOSED = "transport shut down or saw EOF"
# the most of a login node's notice shown to the users
NOTICE_CHARS = 2000

# what sbatch and scancel say when the SLURM controller does not answer in time (it froze for minutes on the
# clusters: "Socket timed out on send/recv operation", "Unable to contact slurm controller (connect failure)"),
# and what the submit script says when it gave sbatch up; a login node not answering in time looks the same
SLURM_STUCK = re.compile(r"timed out|Unable to contact slurm controller|temporarily unable", re.IGNORECASE)


def slurm_stuck(error: Exception) -> bool:
    """Whether a failed command on the cluster met a SLURM (or login node) that did not answer in time, or logins
    the admins closed - worth trying again later, unlike a certificate the cluster refused or input sbatch rejected
    """
    if isinstance(error, AuthenticationException):
        # the key was accepted, then the login node hung up: logins closed by the admins (/etc/nologin), unlike a
        # refused certificate ("Authentication failed.")
        return LOGIN_CLOSED in str(error)
    # also an error raised while handling a timeout: paramiko's "Error reading SSH protocol banner" of a frozen node
    cause = error
    while cause is not None:
        if isinstance(cause, (TimeoutError, CommandTimedOut)):
            return True
        cause = cause.__cause__ or cause.__context__
    return bool(SLURM_STUCK.search(str(error)))


def certificate_expired(cert: str) -> bool:
    """Whether an SSH certificate is past its end; one that cannot be read is left for the login to judge"""
    try:
        certificate = load_ssh_public_identity(cert.encode())
    except (ValueError, TypeError, AttributeError):
        return False
    return isinstance(certificate, SSHCertificate) and certificate.valid_before < time.time()


def get_connection(user: KeycloakUserModel, cluster: ClusterModel) -> Connection:
    """Returns connection object to cluster"""
    # a login with an expired certificate fails anyway, and failed logins count against the account on the cluster
    if certificate_expired(user.cert):
        raise AuthenticationException("The certificate for the cluster expired, log in again")
    pkey = RSAKey.from_private_key(io.StringIO(user.private_key))
    pkey.load_certificate(user.cert)

    con = ClusterConnection(
        host=f"{user.username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey, "allow_agent": False, "look_for_keys": False},
        # an unreachable login node must not block the engine's submits for long
        connect_timeout=30,
    )
    con.cluster_id = cluster.id
    return con


class ClusterConnection(Connection):
    """Connection to a cluster's login node that keeps what the cluster's admins said when it closed the connection
    (/etc/nologin), for the users waiting for the cluster; a login that succeeds clears it
    """

    # a real attribute: fabric turns the unknown ones into config
    cluster_id: Optional[int] = None

    def open(self):
        """Logs in, unless connected already"""
        if self.is_connected:
            return super().open()
        try:
            opened = super().open()
        except AuthenticationException as e:
            if LOGIN_CLOSED in str(e):
                show_notice(self.cluster_id, login_notice(self))
            raise
        show_notice(self.cluster_id, None)
        return opened


def login_notice(con: Connection) -> Optional[str]:
    """What the login node said before it closed the connection: the admins' notice (/etc/nologin) it sends as the
    login banner; paramiko keeps it in the auth handler (get_banner() answers None once the connection is closed)
    """
    banner = getattr(getattr(con.client.get_transport(), "auth_handler", None), "banner", None)
    if not banner:
        return None
    return banner.decode(errors="replace").strip()[:NOTICE_CHARS] or None


def show_notice(cluster_id: int, notice: Optional[str]) -> None:
    """Stores the notice of the cluster's login node (None: it lets the users in), in its own transaction"""
    cluster = ClusterModel.__table__
    with db.engine.begin() as connection:
        connection.execute(
            cluster.update()
            .where(cluster.c.id == cluster_id, cluster.c.notice.is_distinct_from(notice))
            .values(notice=notice)
        )


def fail_submit(simulation: BatchSimulationModel, log: dict) -> None:
    """The simulation could not be submitted: FAILED, with what went wrong for the user to see"""
    # not the whole log: the scripts in it carry the simulation's update key
    logging.error("Submitting simulation %d failed: %s", simulation.id, log.get("error") or log.get("message"))
    logfiles = LogfilesModel(simulation_id=simulation.id)
    logfiles.data = log
    add_object_to_db(logfiles)
    db.session.query(TaskModel).filter(TaskModel.simulation_id == simulation.id).update(
        {TaskModel.task_state: EntityState.FAILED.value}, synchronize_session=False
    )
    update_simulation_state(
        simulation, {"job_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    )


def claim_job_dir(simulation_id: int, job_dir: str) -> bool:
    """Records the job directory before anything is submitted; False when another submit already did

    A crash after this point leaves a directory that can be found (and the simulation is failed on the engine's
    restart), a second submit of the same simulation never starts, and neither does one cancelled meanwhile.
    """
    simulations, batch_simulations = SimulationModel.__table__, BatchSimulationModel.__table__
    still_pending = (
        db.select(simulations.c.id)
        .where(simulations.c.id == simulation_id, simulations.c.job_state == EntityState.PENDING.value)
        .exists()
    )
    claimed = db.session.execute(
        batch_simulations.update()
        .where(batch_simulations.c.id == simulation_id, batch_simulations.c.job_dir.is_(None), still_pending)
        .values(job_dir=job_dir)
    ).rowcount
    db.session.commit()
    return claimed == 1


def submit_simulation(simulation_id: int) -> Optional[bool]:  # skipcq: PY-R1000
    """Submits a stored HPC simulation to its cluster with the user's certificate

    Returns whether the cluster's SLURM answered, None when it was not asked. A SLURM that did not answer in time
    leaves the simulation PENDING, with the job directory of the attempt recorded: the next submit first cancels
    what that attempt left on the cluster. Other failures end it FAILED.
    """
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if simulation is None or simulation.job_state != EntityState.PENDING.value or simulation.array_id is not None:
        return None
    if simulation.job_dir:
        # an attempt that met a stuck SLURM, or a restart of the engine; its script on the login node ends by itself
        # (SBATCH_SECONDS), only then nothing more of it can reach SLURM
        if time.time() - submitted_at(simulation.job_dir) < SUBMIT_SECONDS:
            return None
        answered = cancel_simulation(simulation_id)
        db.session.refresh(simulation)
        if simulation.job_dir or simulation.job_state != EntityState.PENDING.value:
            return answered
    user = db.session.get(KeycloakUserModel, simulation.user_id)
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    if user is None or user.cert is None or user.private_key is None:
        fail_submit(simulation, {"error": "The user has no certificate for the cluster, log in again"})
        return None
    if not result_storage.configured():
        # the jobs report progress and send results through it
        fail_submit(simulation, {"error": "HPC simulations need the results storage, which is not configured"})
        return None
    if not os.environ.get("BACKEND_EXTERNAL_URL"):
        fail_submit(simulation, {"error": "BACKEND_EXTERNAL_URL is not set, the cluster's jobs could not report"})
        return None
    if not os.environ.get("YAPTIDE_TOKEN_SECRET"):
        # the update key would be signed with a secret only this process knows, the backend would reject the reports
        fail_submit(
            simulation, {"error": "YAPTIDE_TOKEN_SECRET is not set, the cluster's reports could not be accepted"}
        )
        return None
    input_dict = simulation.inputs[0].data
    payload_dict = {
        "sim_type": simulation.sim_type,
        "ntasks": len(simulation.tasks),
        "batch_options": input_dict.get("batch_options") or {},
    }
    update_key = encode_simulation_auth_token(simulation.id)
    try:
        with get_connection(user=user, cluster=cluster) as con:
            scratch = con.run("echo $SCRATCH", hide=True, timeout=COMMAND_SECONDS).stdout.split()[0]
            job_dir = f"{scratch}/yaptide_runs/{simulation.id}_{int(time.time() * 1e6)}"
            if not claim_job_dir(simulation.id, job_dir):
                return None
            # readable by the user only: the signed links and the update key are in there
            con.run(f"mkdir -p -m 700 {job_dir}", timeout=COMMAND_SECONDS)
            # uploads to a hung login node are given up too
            con.sftp().get_channel().settimeout(COMMAND_SECONDS)
            files = dict(input_dict["input_files"])
            if simulation.sim_type == SimulationType.SHIELDHIT.value:
                # saves along the way for partial results, in the cluster's copy only: the stored input stays the user's
                set_shieldhit_save_step(files, max(task.requested_primaries or 0 for task in simulation.tasks))
            upload_inputs(con, job_dir, files)
            # signed links the jobs report progress and look for a cancel with, and the key to ask for new ones
            job_links = result_storage.job_links(simulation.id)
            links = json.dumps(dict(job_links, update_key=update_key)).encode()
            con.put(io.BytesIO(links), f"{job_dir}/storage_links.json")
            submit_file, sh_files = prepare_script_files(
                payload_dict=payload_dict, job_dir=job_dir, sim_id=simulation.id, update_key=update_key, con=con
            )
            result: Result = con.run(f"sh {submit_file}", hide=True, warn=True, timeout=SUBMIT_SECONDS)
    except Exception as e:  # skipcq: PYL-W0703
        db.session.rollback()
        if slurm_stuck(e):
            logging.warning("Submitting simulation %d met a stuck cluster, to be repeated: %s", simulation_id, e)
            return False
        fail_submit(db.session.get(BatchSimulationModel, simulation_id), {"error": str(e)})
        # whatever reached the cluster before the error (some jobs, the directory) is cancelled and removed
        cancel_simulation(simulation_id)
        return None

    job_ids = dict(line.split(" id: ") for line in result.stdout.splitlines() if " id: " in line)
    array_id, collect_id = job_ids.get("Job"), job_ids.get("Collect")
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if not (array_id and collect_id and array_id.isdigit() and collect_id.isdigit()):
        if SLURM_STUCK.search(result.stderr):
            logging.warning("SLURM did not answer the submit of simulation %d, to be repeated", simulation_id)
            return False
        log = {"message": "Job submission failed", "submit_stdout": result.stdout, "submit_stderr": result.stderr}
        fail_submit(simulation, {**log, "sh_files": sh_files})
        # the array may have been submitted before the rest failed: it would run for nothing
        cancel_simulation(simulation_id)
        return True
    # stored whatever the state: a simulation cancelled while submitting still needs its ids to cancel the jobs
    db.session.execute(
        BatchSimulationModel.__table__.update()
        .where(BatchSimulationModel.__table__.c.id == simulation_id)
        .values(array_id=int(array_id), collect_id=int(collect_id))
    )
    db.session.commit()
    db.session.refresh(simulation)
    # a cancel stored while submitting found nothing to stop on the cluster yet
    if simulation.job_state == EntityState.CANCELED.value:
        cancel_simulation(simulation_id)
    return True


# the scripts the jobs run, put next to the inputs: the ones merging results need pymchelper, the others the standard
# library only
SCRIPTS = ("watcher.py", "simulation_data_sender.py", "results_uploader.py", "results_merger.py", "result_format.py")


def upload_inputs(con: Connection, job_dir: str, files_dict: dict) -> None:
    """Puts the input files (zipped) and the scripts the jobs run next to them in the job directory"""
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        zip_path = Path(tmp_dir_path) / "input.zip"
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))
        with ZipFile(zip_path, mode="w") as archive:
            for file in Path(tmp_dir_path).iterdir():
                if file.name != "input.zip":
                    archive.write(file, arcname=file.name)
        con.put(zip_path, job_dir)
    for script in SCRIPTS:
        con.put(Path(__file__).parent.resolve() / script, job_dir)


# a job directory as submit_simulation creates it: $SCRATCH/yaptide_runs/<simulation id>_<microseconds>
JOB_DIR_PATTERN = re.compile(r"/[\w./-]+/yaptide_runs/(\d+)_(\d+)")


def submitted_at(job_dir: str) -> float:
    """When the submit that created the job directory started (seconds since the epoch), 0 for a directory this
    backend did not create
    """
    match = JOB_DIR_PATTERN.fullmatch(job_dir)
    return int(match.group(2)) / 1e6 if match else 0.0


def job_tag(job_dir: str) -> str:
    """The comment of every SLURM job of one submit, unique to it like its directory: a cancel finds them by it even
    when sbatch was given up before it told the job id - SLURM may still have taken the job. A comment, not the name:
    the users name their jobs in the batch options.
    """
    return "yaptide_" + job_dir.rsplit("/", 1)[-1]


# the jobs of a simulation, in the order they are cancelled: the reporter first - a cancelled collect would start
# it (it reports a collect that did not succeed); then the collect - cancelling the array first lets SLURM start
# the collect, which then reports FAILED. The submit script writes their ids into the job directory.
# "aggregator": jobs submitted before progress went through storage still have one (test -s skips it otherwise)
SIMULATION_JOBS = ("reporter", "collect", "array", "aggregator")


def forget_job_dir(simulation_id: int) -> None:
    """Nothing of the simulation is left on the cluster to cancel"""
    db.session.execute(
        BatchSimulationModel.__table__.update()
        .where(BatchSimulationModel.__table__.c.id == simulation_id)
        .values(job_dir=None)
    )
    db.session.commit()


def cancel_command(job_dir: str) -> str:
    """The command that cancels the jobs of one submit and then removes its directory, bounded on the login node

    One command, as every command is a round trip. The jobs go by the ids the submit wrote next to them (a job already
    gone from SLURM makes its scancel fail, the rest are still cancelled), then by the submit's comment, which squeue
    shows (scancel filters by name only): the jobs whose id was never written. The directory goes only when squeue
    and that scancel answered.
    """
    quoted = shlex.quote(job_dir)
    cancels = [f"test -s {quoted}/{job}_job_id && scancel `cat {quoted}/{job}_job_id`" for job in SIMULATION_JOBS]
    # %F: the array's job id (of a job not in an array, its own), %k: the comment
    listed = 'JOBS=`squeue -h -u $USER -o "%F %k"`'
    tagged = f"""IDS=`echo "$JOBS" | awk '$2 == "{job_tag(job_dir)}" {{print $1}}' | sort -u`"""
    script = "; ".join([*cancels, f'{listed} && {tagged} && {{ [ -z "$IDS" ] || scancel $IDS; }} && rm -rf {quoted}'])
    return f"timeout {CANCEL_SECONDS} sh -c {shlex.quote(script)}"


def cancel_simulation(simulation_id: int) -> Optional[bool]:
    """Cancels the SLURM jobs of a simulation and removes its directory on the cluster, then forgets the directory;
    returns whether the cluster's SLURM answered, None when it was not asked

    The jobs are found by the ids the submit wrote into the job directory and by the submit's comment, so a submit
    interrupted before its ids reached the database (or before sbatch told them) is cleaned up too. A directory left in
    the database means the cancel is still to be done (the engine repeats it every few minutes). With the user's
    certificate expired, the jobs still stop by themselves, as they find the cancel the engine put into storage
    (yaptide/batch/watcher.py); the directory stays on the cluster.
    """
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if simulation is None or not simulation.job_dir:
        return None
    match = JOB_DIR_PATTERN.fullmatch(simulation.job_dir)
    if not match or int(match.group(1)) != simulation.id:
        # only a directory this backend created goes into a command on the cluster
        logging.error("Simulation %d has an unexpected job directory, nothing is cancelled", simulation.id)
        forget_job_dir(simulation.id)
        return None
    user = db.session.get(KeycloakUserModel, simulation.user_id)
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    try:
        with get_connection(user=user, cluster=cluster) as con:
            result = con.run(cancel_command(simulation.job_dir), hide=True, warn=True, timeout=COMMAND_SECONDS)
    except AuthenticationException as e:
        if slurm_stuck(e):
            logging.warning("The cluster closed logins, cancelling simulation %d is to be repeated", simulation_id)
            return False
        logging.warning("Certificate of simulation %d expired, its jobs stop through storage", simulation.id)
        forget_job_dir(simulation.id)
        return None
    except Exception as e:  # skipcq: PYL-W0703
        logging.error(
            "Cancelling the jobs of simulation %d on the cluster failed, to be repeated: %s", simulation_id, e
        )
        return False if slurm_stuck(e) else None
    if result.exited:
        logging.error(
            "Cancelling the jobs of simulation %d on the cluster failed, to be repeated: %s",
            simulation_id,
            result.stderr.strip()[-500:] or f"exit status {result.exited}",
        )
        # 124: the timeout around the command ended it
        return False if result.exited == 124 or SLURM_STUCK.search(result.stderr) else None
    forget_job_dir(simulation.id)
    return True


def prepare_script_files(
    payload_dict: dict, job_dir: str, sim_id: int, update_key: str, con: Connection
) -> tuple[str, dict]:
    """Writes the job scripts into the job directory; returns the submit script's path and the scripts"""
    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")
    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")
    # the reporter has no script header: the queue placement typed into the array header goes on its command line
    reporter_options = helper_job_sbatch_options(
        payload_dict=payload_dict, sim_id=sim_id, job_dir=job_dir, job_tag=job_tag(job_dir)
    )
    backend_url = os.environ.get("BACKEND_EXTERNAL_URL", "")

    if payload_dict["sim_type"] == SimulationType.FLUKA.value:
        templates = {"submit": SUBMIT_FLUKA, "array": ARRAY_FLUKA_BASH, "collect": COLLECT_FLUKA_BASH}
    else:
        # the tasks' watchers merge partial results with the partial script (FLUKA's tasks save only at the end)
        templates = {
            "submit": SUBMIT_SHIELDHIT,
            "array": ARRAY_SHIELDHIT_BASH,
            "collect": COLLECT_SHIELDHIT_BASH,
            "partial": PARTIAL_SHIELDHIT_BASH,
        }
    common = {"root_dir": job_dir, "sim_id": sim_id, "update_key": update_key, "backend_url": backend_url}
    sh_files = {
        "submit": templates["submit"].format(
            array_options=array_options,
            collect_options=collect_options,
            n_tasks=str(payload_dict["ntasks"]),
            convertmc_version=pymchelper.__version__,
            reporter_options=reporter_options,
            job_tag=job_tag(job_dir),
            sbatch_seconds=SBATCH_SECONDS,
            **common,
        ),
        "array": templates["array"].format(array_header=array_header, n_tasks=str(payload_dict["ntasks"]), **common),
        "collect": templates["collect"].format(
            collect_header=collect_header,
            remove_output_from_workspace="true",
            find_merge_python=FIND_MERGE_PYTHON,
            **common,
        ),
    }
    if "partial" in templates:
        sh_files["partial"] = templates["partial"].format(find_merge_python=FIND_MERGE_PYTHON, **common)
    paths = {
        "submit": f"{job_dir}/yaptide_submitter.sh",
        "array": f"{job_dir}/array_script.sh",
        "collect": f"{job_dir}/collect_script.sh",
        "partial": f"{job_dir}/partial_script.sh",
    }
    # put as files: one round trip each and no quoting of the scripts through a shell command
    for name, script in sh_files.items():
        con.put(io.BytesIO(script.encode()), paths[name])
    con.run("chmod +x " + " ".join(shlex.quote(paths[name]) for name in sh_files), timeout=COMMAND_SECONDS)
    return paths["submit"], sh_files
