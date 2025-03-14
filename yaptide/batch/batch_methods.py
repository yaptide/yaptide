import io
import json
import logging
import os
import tempfile
import requests
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
import sqlalchemy as db

import pymchelper
from fabric import Connection, Result
from paramiko import RSAKey

from yaptide.batch.shieldhit_string_templates import (ARRAY_SHIELDHIT_BASH, COLLECT_SHIELDHIT_BASH, SUBMIT_SHIELDHIT)
from yaptide.batch.fluka_string_templates import (ARRAY_FLUKA_BASH, COLLECT_FLUKA_BASH, SUBMIT_FLUKA)
from yaptide.batch.utils.utils import (convert_dict_to_sbatch_options, extract_sbatch_header)
from yaptide.persistence.models import (BatchSimulationModel, ClusterModel, KeycloakUserModel, UserModel)
from yaptide.utils.enums import EntityState, SimulationType
from yaptide.utils.sim_utils import write_simulation_input_files

from yaptide.admin.db_manage import TableTypes, connect_to_db
from yaptide.utils.helper_worker import celery_app


def get_user(db_con, metadata, userId):
    """Queries database for user"""
    users = metadata.tables[TableTypes.User.name]
    keycloackUsers = metadata.tables[TableTypes.KeycloakUser.name]
    stmt = db.select(users,
                     keycloackUsers).select_from(users).join(keycloackUsers,
                                                             KeycloakUserModel.id == UserModel.id).filter_by(id=userId)
    try:
        user: KeycloakUserModel = db_con.execute(stmt).first()
    except Exception:
        logging.error('Error getting user object wiht id: %s from database', str(userId))
        return None
    return user


def get_cluster(db_con, metadata, clusterId):
    """Queries database for user"""
    clusters = metadata.tables[TableTypes.Cluster.name]
    stmt = db.select(clusters).filter_by(id=clusterId)
    try:
        cluster: ClusterModel = db_con.execute(stmt).first()
    except Exception:
        logging.error('Error getting cluster object with id: %s from database', str(clusterId))
        return None
    return cluster


def get_connection(user: KeycloakUserModel, cluster: ClusterModel) -> Connection:
    """Returns connection object to cluster"""
    pkey = RSAKey.from_private_key(io.StringIO(user.private_key))
    pkey.load_certificate(user.cert)

    con = Connection(host=f"{user.username}@{cluster.cluster_name}",
                     connect_kwargs={
                         "pkey": pkey,
                         "allow_agent": False,
                         "look_for_keys": False
                     })
    return con


def post_update(dict_to_send):
    """For sending requests with information to flask"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    return requests.Session().post(url=f"{flask_url}/jobs", json=dict_to_send)


@celery_app.task()
def submit_job(  # skipcq: PY-R1000
        payload_dict: dict, files_dict: dict, userId: int, clusterId: int, sim_id: int, update_key: str):
    """Submits job to cluster"""
    utc_now = int(datetime.utcnow().timestamp() * 1e6)
    try:
        db_con, metadata, _ = connect_to_db(
        )  # Connection to database and quering objects looks like that because celery task works outside flask context
    except Exception as e:
        logging.error('Async worker couldn\'t connect to db. Error message:"%s"', str(e))

    user = get_user(db_con=db_con, metadata=metadata, userId=userId)
    cluster = get_cluster(db_con=db_con, metadata=metadata, clusterId=clusterId)

    if user.cert is None or user.private_key is None:
        dict_to_send = {
            "sim_id": sim_id,
            "job_state": EntityState.FAILED.value,
            "update_key": update_key,
            "log": {
                "error": f"User {user.username} has no certificate or private key"
            }
        }
        post_update(dict_to_send)
        return

    try:
        con = get_connection(user=user, cluster=cluster)
        fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    except Exception as e:
        dict_to_send = {
            "sim_id": sim_id,
            "job_state": EntityState.FAILED.value,
            "update_key": update_key,
            "log": {
                "error": str(e)
            }
        }
        post_update(dict_to_send)
        return

    scratch = fabric_result.stdout.split()[0]
    logging.debug("Scratch directory: %s", scratch)

    job_dir = f"{scratch}/yaptide_runs/{utc_now}"
    logging.debug("Job directory: %s", job_dir)

    try:
        con.run(f"mkdir -p {job_dir}")
    except Exception as e:
        dict_to_send = {"sim_id": sim_id, "job_state": EntityState.FAILED.value, "update_key": update_key}
        post_update(dict_to_send)
        return
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        logging.debug("Preparing simulation input in: %s", tmp_dir_path)
        zip_path = Path(tmp_dir_path) / "input.zip"
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))
        logging.debug("Zipping simulation input to %s", zip_path)
        with ZipFile(zip_path, mode="w") as archive:
            for file in Path(tmp_dir_path).iterdir():
                if file.name == "input.zip":
                    continue
                archive.write(file, arcname=file.name)
        con.put(zip_path, job_dir)
        logging.debug("Transfering simulation input %s to %s", zip_path, job_dir)

    WATCHER_SCRIPT = Path(__file__).parent.resolve() / "watcher.py"
    SIMULATION_DATA_SENDER_SCRIPT = Path(__file__).parent.resolve() / "simulation_data_sender.py"

    logging.debug("Transfering watcher script %s to %s", WATCHER_SCRIPT, job_dir)
    con.put(WATCHER_SCRIPT, job_dir)
    logging.debug("Transfering result sender script %s to %s", SIMULATION_DATA_SENDER_SCRIPT, job_dir)
    con.put(SIMULATION_DATA_SENDER_SCRIPT, job_dir)

    submit_file, sh_files = prepare_script_files(payload_dict=payload_dict,
                                                 job_dir=job_dir,
                                                 sim_id=sim_id,
                                                 update_key=update_key,
                                                 con=con)

    array_id = collect_id = None
    if not submit_file.startswith(job_dir):
        logging.error("Invalid submit file path: %s", submit_file)
        dict_to_send = {
            "sim_id": sim_id,
            "job_state": EntityState.FAILED.value,
            "update_key": update_key,
            "log": {
                "error": "Job submission failed due to invalid submit file path"
            }
        }
        post_update(dict_to_send)
        return
    fabric_result: Result = con.run(f'sh {submit_file}', hide=True)
    submit_stdout = fabric_result.stdout
    submit_stderr = fabric_result.stderr
    for line in submit_stdout.split("\n"):
        if line.startswith("Job id"):
            try:
                array_id = int(line.split()[-1])
            except (ValueError, IndexError):
                logging.error("Could not parse array id from line: %s", line)
        if line.startswith("Collect id"):
            try:
                collect_id = int(line.split()[-1])
            except (ValueError, IndexError):
                logging.error("Could not parse collect id from line: %s", line)

    if array_id is None or collect_id is None:
        logging.debug("Job submission failed")
        logging.debug("Sbatch stdout: %s", submit_stdout)
        logging.debug("Sbatch stderr: %s", submit_stderr)
        dict_to_send = {
            "sim_id": sim_id,
            "job_state": EntityState.FAILED.value,
            "update_key": update_key,
            "log": {
                "message": "Job submission failed",
                "submit_stdout": submit_stdout,
                "sh_files": sh_files,
                "submit_stderr": submit_stderr
            }
        }
        post_update(dict_to_send)
        return

    dict_to_send = {
        "sim_id": sim_id,
        "update_key": update_key,
        "job_dir": job_dir,
        "array_id": array_id,
        "collect_id": collect_id,
        "submit_stdout": submit_stdout,
        "sh_files": sh_files
    }
    post_update(dict_to_send)
    return


def prepare_script_files(payload_dict: dict, job_dir: str, sim_id: int, update_key: str,
                         con: Connection) -> tuple[str, dict]:
    """Prepares script files to run them on cluster"""
    submit_file = f'{job_dir}/yaptide_submitter.sh'
    array_file = f'{job_dir}/array_script.sh'
    collect_file = f'{job_dir}/collect_script.sh'

    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")

    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")

    backend_url = os.environ.get("BACKEND_EXTERNAL_URL", "")

    if payload_dict['sim_type'] == SimulationType.FLUKA.value:
        submit_template = SUBMIT_FLUKA
        array_template = ARRAY_FLUKA_BASH
        collect_template = COLLECT_FLUKA_BASH
    elif payload_dict['sim_type'] == SimulationType.SHIELDHIT.value:
        submit_template = SUBMIT_SHIELDHIT
        array_template = ARRAY_SHIELDHIT_BASH
        collect_template = COLLECT_SHIELDHIT_BASH
    else:
        # Ready for future simulators
        submit_template = ""
        array_template = ""
        collect_template = ""

    submit_script = submit_template.format(array_options=array_options,
                                           collect_options=collect_options,
                                           root_dir=job_dir,
                                           n_tasks=str(payload_dict["ntasks"]),
                                           convertmc_version=pymchelper.__version__)
    array_script = array_template.format(array_header=array_header,
                                         root_dir=job_dir,
                                         sim_id=sim_id,
                                         update_key=update_key,
                                         backend_url=backend_url)
    collect_script = collect_template.format(collect_header=collect_header,
                                             root_dir=job_dir,
                                             remove_output_from_workspace="true",
                                             sim_id=sim_id,
                                             update_key=update_key,
                                             backend_url=backend_url)

    con.run(f'echo \'{array_script}\' >> {array_file}')
    con.run(f'chmod +x {array_file}')
    con.run(f'echo \'{submit_script}\' >> {submit_file}')
    con.run(f'chmod +x {submit_file}')
    con.run(f'echo \'{collect_script}\' >> {collect_file}')
    con.run(f'chmod +x {collect_file}')

    return submit_file, {"submit": submit_script, "array": array_script, "collect": collect_script}


def get_job_status(simulation: BatchSimulationModel, user: KeycloakUserModel, cluster: ClusterModel) -> dict:
    """Get SLURM job status"""
    array_id = simulation.array_id
    collect_id = simulation.collect_id

    con = get_connection(user=user, cluster=cluster)

    fabric_result: Result = con.run(f'sacct -j {array_id} --format State', hide=True)
    job_state = fabric_result.stdout.split()[-1].split()[0]

    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]

    if job_state == "FAILED" or collect_state == "FAILED":
        return {"job_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    if collect_state == "COMPLETED":
        return {"job_state": EntityState.COMPLETED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    if collect_state == "RUNNING":
        logging.debug("Collect job is in RUNNING state")
        return {"job_state": EntityState.MERGING_RUNNING.value}
    if job_state == "COMPLETED" and collect_state == "PENDING":
        logging.debug("Collect job is in PENDING state")
        return {"job_state": EntityState.MERGING_QUEUED.value}
    if job_state == "RUNNING":
        logging.debug("Main job is in RUNNING state")
    if job_state == "PENDING":
        logging.debug("Main job is in PENDING state")

    return {"job_state": EntityState.RUNNING.value}


def get_job_results(simulation: BatchSimulationModel, user: KeycloakUserModel, cluster: ClusterModel) -> dict:
    """Returns simulation results"""
    job_dir = simulation.job_dir
    collect_id = simulation.collect_id

    con = get_connection(user=user, cluster=cluster)

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
    return {"message": "Results not available"}


def delete_job(simulation: BatchSimulationModel, user: KeycloakUserModel,
               cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    job_dir = simulation.job_dir
    array_id = simulation.array_id
    collect_id = simulation.collect_id

    try:
        con = get_connection(user=user, cluster=cluster)

        con.run(f'scancel {array_id}')
        con.run(f'scancel {collect_id}')
        con.run(f'rm -rf {job_dir}')
    except Exception as e:  # skipcq: PYL-W0703
        logging.error(e)
        return {"message": "Job cancelation failed"}, 500

    return {"message": "Job canceled"}, 200
