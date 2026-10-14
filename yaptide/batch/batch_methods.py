import io
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pymchelper
from fabric import Connection, Result
from paramiko import RSAKey

from yaptide.batch.shieldhit_string_templates import (
    AGGREGATOR_SHIELDHIT_BASH,
    ARRAY_SHIELDHIT_BASH,
    COLLECT_SHIELDHIT_BASH,
    SUBMIT_SHIELDHIT,
)
from yaptide.batch.fluka_string_templates import ARRAY_FLUKA_BASH, COLLECT_FLUKA_BASH, SUBMIT_FLUKA
from yaptide.batch.utils.utils import (
    convert_dict_to_aggregator_sbatch_options,
    convert_dict_to_sbatch_options,
    extract_aggregator_header,
    extract_sbatch_header,
)
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import add_object_to_db, update_simulation_state
from yaptide.persistence.models import BatchSimulationModel, ClusterModel, KeycloakUserModel, LogfilesModel
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, SimulationType
from yaptide.utils.sim_utils import write_simulation_input_files


def get_connection(user: KeycloakUserModel, cluster: ClusterModel) -> Connection:
    """Returns connection object to cluster"""
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
    update_simulation_state(
        simulation, {"job_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    )


def claim_job_dir(simulation_id: int, job_dir: str) -> bool:
    """Records the job directory before anything is submitted; False when another submit already did

    A crash after this point leaves a directory that can be found (and the simulation is failed on the engine's
    restart), and a second submit of the same simulation never starts.
    """
    claimed = db.session.execute(
        BatchSimulationModel.__table__.update()
        .where(BatchSimulationModel.__table__.c.id == simulation_id, BatchSimulationModel.__table__.c.job_dir.is_(None))
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
            scratch = con.run("echo $SCRATCH", hide=True).stdout.split()[0]
            job_dir = f"{scratch}/yaptide_runs/{simulation.id}_{int(datetime.utcnow().timestamp() * 1e6)}"
            if not claim_job_dir(simulation.id, job_dir):
                return
            con.run(f"mkdir -p {job_dir}")
            upload_inputs(con, job_dir, input_dict["input_files"])
            submit_file, sh_files = prepare_script_files(
                payload_dict=payload_dict, job_dir=job_dir, sim_id=simulation.id, update_key=update_key, con=con
            )
            result: Result = con.run(f"sh {submit_file}", hide=True, warn=True)
    except Exception as e:  # skipcq: PYL-W0703
        db.session.rollback()
        fail_submit(db.session.get(BatchSimulationModel, simulation_id), {"error": str(e)})
        return

    job_ids = dict(line.split(" id: ") for line in result.stdout.splitlines() if " id: " in line)
    array_id, collect_id = job_ids.get("Job"), job_ids.get("Collect")
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if not (array_id and collect_id and array_id.isdigit() and collect_id.isdigit()):
        log = {"message": "Job submission failed", "submit_stdout": result.stdout, "submit_stderr": result.stderr}
        fail_submit(simulation, {**log, "sh_files": sh_files})
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
    for script in ("watcher.py", "simulation_data_sender.py", "aggregator.py", "results_uploader.py"):
        con.put(Path(__file__).parent.resolve() / script, job_dir)


def cancel_simulation(simulation_id: int) -> None:
    """Cancels the SLURM jobs of a cancelled simulation and removes its directory on the cluster

    Possible only while the user's certificate is valid; otherwise the jobs run to their end and what they report
    is ignored, as the simulation is final.
    """
    simulation = db.session.get(BatchSimulationModel, simulation_id)
    if simulation is None or simulation.array_id is None:
        return
    user = db.session.get(KeycloakUserModel, simulation.user_id)
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    job_dir = simulation.job_dir
    try:
        with get_connection(user=user, cluster=cluster) as con:
            # collect first - cancelling the array first lets SLURM start the collect, which then reports FAILED;
            # a job already gone from SLURM makes scancel fail, the rest must still be cancelled (warn)
            con.run(f"scancel {simulation.collect_id}", warn=True)
            con.run(f"scancel {simulation.array_id}", warn=True)
            # by id, not by name - several yaptide deployments may share one cluster account
            for helper_job in ("aggregator", "reporter"):
                con.run(
                    f"test -s {job_dir}/{helper_job}_job_id && scancel `cat {job_dir}/{helper_job}_job_id`", warn=True
                )
            con.run(f"rm -rf {job_dir}", warn=True)
    except Exception as e:  # skipcq: PYL-W0703
        logging.error("Cancelling the jobs of simulation %d on the cluster failed: %s", simulation_id, e)


def prepare_script_files(
    payload_dict: dict, job_dir: str, sim_id: int, update_key: str, con: Connection
) -> tuple[str, dict]:
    """Prepares script files to run them on cluster"""
    submit_file = f"{job_dir}/yaptide_submitter.sh"
    array_file = f"{job_dir}/array_script.sh"
    collect_file = f"{job_dir}/collect_script.sh"
    aggregator_file = f"{job_dir}/aggregator_script.sh"

    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")

    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")

    aggregator_options = convert_dict_to_aggregator_sbatch_options(
        payload_dict=payload_dict, sim_id=sim_id, job_dir=job_dir
    )
    reporter_options = convert_dict_to_aggregator_sbatch_options(
        payload_dict=payload_dict, sim_id=sim_id, job_dir=job_dir, role="reporter"
    )
    # options typed as #SBATCH lines of the array header apply to the aggregator too, the command line ones win
    aggregator_header = extract_aggregator_header(array_header)

    backend_url = os.environ.get("BACKEND_EXTERNAL_URL", "")

    if payload_dict["sim_type"] == SimulationType.FLUKA.value:
        submit_template = SUBMIT_FLUKA
        array_template = ARRAY_FLUKA_BASH
        collect_template = COLLECT_FLUKA_BASH
        aggregator_template = ""
    elif payload_dict["sim_type"] == SimulationType.SHIELDHIT.value:
        submit_template = SUBMIT_SHIELDHIT
        array_template = ARRAY_SHIELDHIT_BASH
        collect_template = COLLECT_SHIELDHIT_BASH
        aggregator_template = AGGREGATOR_SHIELDHIT_BASH
    else:
        # Ready for future simulators
        submit_template = ""
        array_template = ""
        collect_template = ""
        aggregator_template = ""

    submit_script = submit_template.format(
        array_options=array_options,
        collect_options=collect_options,
        root_dir=job_dir,
        n_tasks=str(payload_dict["ntasks"]),
        convertmc_version=pymchelper.__version__,
        sim_id=sim_id,
        update_key=update_key,
        backend_url=backend_url,
        aggregator_options=aggregator_options,
        reporter_options=reporter_options,
    )
    array_script = array_template.format(
        array_header=array_header, root_dir=job_dir, sim_id=sim_id, update_key=update_key, backend_url=backend_url
    )
    collect_script = collect_template.format(
        collect_header=collect_header,
        root_dir=job_dir,
        remove_output_from_workspace="true",
        sim_id=sim_id,
        update_key=update_key,
        backend_url=backend_url,
    )

    con.run(f"echo '{array_script}' >> {array_file}")
    con.run(f"chmod +x {array_file}")
    con.run(f"echo '{submit_script}' >> {submit_file}")
    con.run(f"chmod +x {submit_file}")
    con.run(f"echo '{collect_script}' >> {collect_file}")
    con.run(f"chmod +x {collect_file}")

    sh_files = {"submit": submit_script, "array": array_script, "collect": collect_script}

    if aggregator_template:
        aggregator_script = aggregator_template.format(
            aggregator_header=aggregator_header,
            root_dir=job_dir,
            n_tasks=str(payload_dict["ntasks"]),
            sim_id=sim_id,
            update_key=update_key,
            backend_url=backend_url,
        )
        con.run(f"echo '{aggregator_script}' >> {aggregator_file}")
        con.run(f"chmod +x {aggregator_file}")
        sh_files["aggregator"] = aggregator_script

    return submit_file, sh_files
