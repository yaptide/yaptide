import io
import json
import tempfile

import logging
import os

from zipfile import ZipFile
from datetime import datetime
from pathlib import Path

from fabric import Connection, Result
from paramiko import RSAKey
import pymchelper

from yaptide.batch.string_templates import (
    SUBMIT_SHIELDHIT,
    ARRAY_SHIELDHIT_BASH,
    COLLECT_BASH
)
from yaptide.batch.utils.utils import extract_sbatch_header, convert_dict_to_sbatch_options
from yaptide.persistence.models import KeycloakUserModel, ClusterModel, BatchSimulationModel
from yaptide.utils.sim_utils import write_simulation_input_files
from yaptide.utils.enums import EntityState


def get_connection(user: KeycloakUserModel, cluster: ClusterModel) -> Connection:
    """Returns connection object to cluster"""
    pkey = RSAKey.from_private_key(io.StringIO(user.private_key))
    pkey.load_certificate(user.cert)

    con = Connection(
        host=f"{user.username}@{cluster.cluster_name}",
        connect_kwargs={
            "pkey": pkey,
            "allow_agent": False,
            "look_for_keys": False
        }
    )
    return con


def submit_job(payload_dict: dict, files_dict: dict, user: KeycloakUserModel,
               cluster: ClusterModel, sim_id: int, update_key: str) -> dict:
    """Dummy version of submit_job"""
    utc_time = int(datetime.utcnow().timestamp()*1e6)

    con = get_connection(user=user, cluster=cluster)

    fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = fabric_result.stdout.split()[0]

    job_dir = f"{scratch}/yaptide_runs/{utc_time}"

    con.run(f"mkdir -p {job_dir}")
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        zip_path = Path(tmp_dir_path) / "input.zip"
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))
        with ZipFile(zip_path, mode="w") as archive:
            for file in Path(tmp_dir_path).iterdir():
                if file.name == "input.zip":
                    continue
                archive.write(file, arcname=file.name)
        con.put(zip_path, job_dir)

    WATCHER_SCRIPT = Path(__file__).parent.resolve() / "watcher.py"
    con.put(WATCHER_SCRIPT, job_dir)

    submit_file, sh_files = prepare_script_files(
        payload_dict=payload_dict, job_dir=job_dir, sim_id=sim_id, update_key=update_key, con=con)

    array_id = collect_id = None
    fabric_result: Result = con.run(f'sh {submit_file}', hide=True)
    submit_stdout = fabric_result.stdout
    for line in submit_stdout.split("\n"):
        if line.startswith("Job id"):
            array_id = line.split()[-1]
        if line.startswith("Collect id"):
            collect_id = line.split()[-1]

    if array_id is None or collect_id is None:
        return {
            "message": "Job submission failed",
            "submit_stdout": submit_stdout,
            "sh_files": sh_files
        }
    return {
        "message": "Job submitted",
        "folder_name": utc_time,
        "array_id": array_id,
        "collect_id": collect_id,
        "submit_stdout": submit_stdout,
        "sh_files": sh_files
    }


def prepare_script_files(payload_dict: dict, job_dir: str, sim_id: int,
                         update_key: str, con: Connection) -> tuple[str, dict]:
    """Prepares script files to run them on cluster"""
    submit_file = f'{job_dir}/yaptide_submitter.sh'
    array_file = f'{job_dir}/array_script.sh'
    collect_file = f'{job_dir}/collect_script.sh'

    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")

    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")

    backend_url = os.environ.get("BACKEND_EXTERNAL_URL", "")

    submit_script = SUBMIT_SHIELDHIT.format(
        array_options=array_options,
        collect_options=collect_options,
        root_dir=job_dir,
        n_tasks=str(payload_dict["ntasks"]),
        convertmc_version=pymchelper.__version__
    )
    array_script = ARRAY_SHIELDHIT_BASH.format(
        array_header=array_header,
        root_dir=job_dir,
        sim_id=sim_id,
        update_key=update_key,
        backend_url=backend_url
    )
    collect_script = COLLECT_BASH.format(
        collect_header=collect_header,
        root_dir=job_dir,
        clear_bdos="true"
    )

    con.run(f'echo \'{array_script}\' >> {array_file}')
    con.run(f'chmod +x {array_file}')
    con.run(f'echo \'{submit_script}\' >> {submit_file}')
    con.run(f'chmod +x {submit_file}')
    con.run(f'echo \'{collect_script}\' >> {collect_file}')
    con.run(f'chmod +x {collect_file}')

    return submit_file, {
        "submit": submit_script,
        "array": array_script,
        "collect": collect_script
    }


def get_job_status(simulation: BatchSimulationModel, user: KeycloakUserModel, cluster: ClusterModel) -> dict:
    """Dummy version of get_job_status"""
    array_id = simulation.array_id
    collect_id = simulation.collect_id

    con = get_connection(user=user, cluster=cluster)

    fabric_result: Result = con.run(f'sacct -j {array_id} --format State', hide=True)
    job_state = fabric_result.stdout.split()[-1].split()[0]

    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]

    if job_state == "FAILED" or collect_state == "FAILED":
        return {
            "job_state": EntityState.FAILED.value
        }
    if collect_state == "COMPLETED":
        return {
            "job_state": EntityState.COMPLETED.value,
            "end_time": datetime.utcnow().isoformat(sep=" ")
        }
    if collect_state == "RUNNING":
        logging.debug("Collect job is in RUNNING state")
    if job_state == "RUNNING":
        logging.debug("Main job is in RUNNING state")
    if collect_state == "PENDING":
        logging.debug("Collect job is in PENDING state")
    if job_state == "PENDING":
        logging.debug("Main job is in PENDING state")

    return {
        "job_state": EntityState.RUNNING.value
    }


def get_job_results(simulation: BatchSimulationModel, user: KeycloakUserModel, cluster: ClusterModel) -> dict:
    """Returns simulation results"""
    folder_name = simulation.folder_name
    collect_id = simulation.collect_id

    con = get_connection(user=user, cluster=cluster)

    fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = fabric_result.stdout.split()[0]

    job_dir = f"{scratch}/yaptide_runs/{folder_name}"
    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]

    if collect_state == "COMPLETED":
        fabric_result: Result = con.run(f'ls -f {job_dir}/output | grep .json', hide=True)
        result_estimators = []
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            for filename in fabric_result.stdout.split():
                file_path = Path(tmp_dir_path, filename)
                with open(file_path, "wb") as writer:
                    con.get(f'{job_dir}/output/{filename}', writer)
                with open(file_path, "r") as json_file:
                    est_dict = json.load(json_file)
                    est_dict["name"] = filename.split('.')[0]
                    result_estimators.append(est_dict)

        return {"estimators": result_estimators}
    return {
        "message": "Results not available"
    }


def delete_job(simulation: BatchSimulationModel,
               user: KeycloakUserModel,
               cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    logging.info("Deleting job %s for user %s on cluster %s", simulation.job_id, user.username, cluster.cluster_name)
    return {"message": "Not implemented yet"}, 404
