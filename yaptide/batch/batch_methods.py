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
from zipfile import ZipFile

import pymchelper
from cryptography.hazmat.primitives.serialization import SSHCertificate, load_ssh_public_identity
from fabric import Connection, Result
from paramiko import AuthenticationException, RSAKey

from yaptide.batch.shieldhit_string_templates import (
    ARRAY_SHIELDHIT_BASH,
    COLLECT_SHIELDHIT_BASH,
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
from yaptide.utils.sim_utils import write_simulation_input_files


# a command on the login node that does not end in this time is given up (a hung login node must not hold one of
# the engine's few connections forever); the submit script waits for sbatch several times
COMMAND_SECONDS = 60
SUBMIT_SECONDS = 300


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

    con = Connection(
        host=f"{user.username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey, "allow_agent": False, "look_for_keys": False},
        # an unreachable login node must not block the engine's submits for long
        connect_timeout=30,
    )
    return con


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


def submit_simulation(simulation_id: int) -> None:  # skipcq: PY-R1000
    """Submits a stored HPC simulation to its cluster with the user's certificate; failures end it FAILED"""
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if simulation is None or simulation.job_state != EntityState.PENDING.value or simulation.job_dir:
        return
    user = db.session.get(KeycloakUserModel, simulation.user_id)
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    if user is None or user.cert is None or user.private_key is None:
        fail_submit(simulation, {"error": "The user has no certificate for the cluster, log in again"})
        return
    if not result_storage.configured():
        # the jobs report progress and send results through it
        fail_submit(simulation, {"error": "HPC simulations need the results storage, which is not configured"})
        return
    if not os.environ.get("BACKEND_EXTERNAL_URL"):
        fail_submit(simulation, {"error": "BACKEND_EXTERNAL_URL is not set, the cluster's jobs could not report"})
        return
    if not os.environ.get("YAPTIDE_TOKEN_SECRET"):
        # the update key would be signed with a secret only this process knows, the backend would reject the reports
        fail_submit(
            simulation, {"error": "YAPTIDE_TOKEN_SECRET is not set, the cluster's reports could not be accepted"}
        )
        return
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
            job_dir = f"{scratch}/yaptide_runs/{simulation.id}_{int(datetime.utcnow().timestamp() * 1e6)}"
            if not claim_job_dir(simulation.id, job_dir):
                return
            # readable by the user only: the signed links and the update key are in there
            con.run(f"mkdir -p -m 700 {job_dir}", timeout=COMMAND_SECONDS)
            upload_inputs(con, job_dir, input_dict["input_files"])
            # signed links the jobs report progress and look for a cancel with
            links = json.dumps(result_storage.job_links(simulation.id)).encode()
            con.put(io.BytesIO(links), f"{job_dir}/storage_links.json")
            submit_file, sh_files = prepare_script_files(
                payload_dict=payload_dict, job_dir=job_dir, sim_id=simulation.id, update_key=update_key, con=con
            )
            result: Result = con.run(f"sh {submit_file}", hide=True, warn=True, timeout=SUBMIT_SECONDS)
    except Exception as e:  # skipcq: PYL-W0703
        db.session.rollback()
        fail_submit(db.session.get(BatchSimulationModel, simulation_id), {"error": str(e)})
        # whatever reached the cluster before the error (some jobs, the directory) is cancelled and removed
        cancel_simulation(simulation_id)
        return

    job_ids = dict(line.split(" id: ") for line in result.stdout.splitlines() if " id: " in line)
    array_id, collect_id = job_ids.get("Job"), job_ids.get("Collect")
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if not (array_id and collect_id and array_id.isdigit() and collect_id.isdigit()):
        log = {"message": "Job submission failed", "submit_stdout": result.stdout, "submit_stderr": result.stderr}
        fail_submit(simulation, {**log, "sh_files": sh_files})
        # the array may have been submitted before the rest failed: it would run for nothing
        cancel_simulation(simulation_id)
        return
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
    for script in ("watcher.py", "simulation_data_sender.py", "results_uploader.py"):
        con.put(Path(__file__).parent.resolve() / script, job_dir)


# a job directory as submit_simulation creates it: $SCRATCH/yaptide_runs/<simulation id>_<microseconds>
JOB_DIR_PATTERN = re.compile(r"/[\w./-]+/yaptide_runs/(\d+)_\d+")
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


def cancel_simulation(simulation_id: int) -> None:
    """Cancels the SLURM jobs of a simulation and removes its directory on the cluster, then forgets the directory

    The jobs are found by the ids the submit wrote into the job directory, so a submit interrupted before its ids
    reached the database is cleaned up too. A directory left in the database means the cancel is still to be done
    (the engine's sweep repeats it). With the user's certificate expired, the jobs still stop by themselves, as they
    find the cancel the engine put into storage (yaptide/batch/watcher.py); the directory stays on the cluster.
    """
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if simulation is None or not simulation.job_dir:
        return
    match = JOB_DIR_PATTERN.fullmatch(simulation.job_dir)
    if not match or int(match.group(1)) != simulation.id:
        # only a directory this backend created goes into a command on the cluster
        logging.error("Simulation %d has an unexpected job directory, nothing is cancelled", simulation.id)
        forget_job_dir(simulation.id)
        return
    job_dir = shlex.quote(simulation.job_dir)
    user = db.session.get(KeycloakUserModel, simulation.user_id)
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    try:
        with get_connection(user=user, cluster=cluster) as con:
            # one command, as every command is a round trip; a job already gone from SLURM makes its scancel fail,
            # the rest are still cancelled
            cancels = "; ".join(
                f"test -s {job_dir}/{job}_job_id && scancel `cat {job_dir}/{job}_job_id`" for job in SIMULATION_JOBS
            )
            con.run(f"{cancels}; rm -rf {job_dir}", warn=True, timeout=COMMAND_SECONDS)
    except AuthenticationException:
        logging.warning("Certificate of simulation %d expired, its jobs stop through storage", simulation.id)
    except Exception as e:  # skipcq: PYL-W0703
        logging.error(
            "Cancelling the jobs of simulation %d on the cluster failed, to be repeated: %s", simulation_id, e
        )
        return
    forget_job_dir(simulation.id)


def prepare_script_files(
    payload_dict: dict, job_dir: str, sim_id: int, update_key: str, con: Connection
) -> tuple[str, dict]:
    """Writes the job scripts into the job directory; returns the submit script's path and the scripts"""
    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")
    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")
    # the reporter has no script header: the queue placement typed into the array header goes on its command line
    reporter_options = helper_job_sbatch_options(payload_dict=payload_dict, sim_id=sim_id, job_dir=job_dir)
    backend_url = os.environ.get("BACKEND_EXTERNAL_URL", "")

    if payload_dict["sim_type"] == SimulationType.FLUKA.value:
        templates = {"submit": SUBMIT_FLUKA, "array": ARRAY_FLUKA_BASH, "collect": COLLECT_FLUKA_BASH}
    else:
        templates = {"submit": SUBMIT_SHIELDHIT, "array": ARRAY_SHIELDHIT_BASH, "collect": COLLECT_SHIELDHIT_BASH}
    common = {"root_dir": job_dir, "sim_id": sim_id, "update_key": update_key, "backend_url": backend_url}
    sh_files = {
        "submit": templates["submit"].format(
            array_options=array_options,
            collect_options=collect_options,
            n_tasks=str(payload_dict["ntasks"]),
            convertmc_version=pymchelper.__version__,
            reporter_options=reporter_options,
            **common,
        ),
        "array": templates["array"].format(array_header=array_header, n_tasks=str(payload_dict["ntasks"]), **common),
        "collect": templates["collect"].format(
            collect_header=collect_header, remove_output_from_workspace="true", **common
        ),
    }
    paths = {
        "submit": f"{job_dir}/yaptide_submitter.sh",
        "array": f"{job_dir}/array_script.sh",
        "collect": f"{job_dir}/collect_script.sh",
    }
    # put as files: one round trip each and no quoting of the scripts through a shell command
    for name, script in sh_files.items():
        con.put(io.BytesIO(script.encode()), paths[name])
    con.run("chmod +x " + " ".join(shlex.quote(path) for path in paths.values()), timeout=COMMAND_SECONDS)
    return paths["submit"], sh_files
