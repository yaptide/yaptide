import io
import json
import tempfile

import logging

from zipfile import ZipFile
from datetime import datetime
from pathlib import Path

from fabric import Connection, Result
from paramiko import Ed25519Key
import pymchelper

from yaptide.batch.string_templates import (
    SUBMIT_SHIELDHIT,
    ARRAY_SHIELDHIT_BASH,
    COLLECT_BASH
)
from yaptide.batch.utils.utils import extract_sbatch_header, convert_dict_to_sbatch_options
from yaptide.persistence.models import SimulationModel, ClusterModel
from yaptide.utils.sim_utils import (
    files_dict_with_adjusted_primaries,
    write_simulation_input_files
)


def submit_job(payload_dict: dict, cluster: ClusterModel) -> dict:
    """Dummy version of submit_job"""
    utc_time = int(datetime.utcnow().timestamp()*1e6)
    pkey = Ed25519Key(file_obj=io.StringIO(cluster.cluster_ssh_key))
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )

    fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = fabric_result.stdout.split()[0]

    job_dir = f"{scratch}/yaptide_runs/{utc_time}"

    # since it is not obligatory for UI to provide ntasks parameters it is set here for sure
    # if it is provided it will be overwritten by itself so nothing will change

    con.run(f"mkdir -p {job_dir}")
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        zip_path = Path(tmp_dir_path) / "input.zip"
        files_dict = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))
        with ZipFile(zip_path, mode="w") as archive:
            for file in Path(tmp_dir_path).iterdir():
                if file.name == "input.zip":
                    continue
                archive.write(file, arcname=file.name)
        con.put(zip_path, job_dir)

    WATCHER_SCRIPT = Path(__file__).parent.resolve() / "watcher.py"
    con.put(WATCHER_SCRIPT, job_dir)

    submit_file, sh_files = prepare_script_files(payload_dict=payload_dict, job_dir=job_dir, con=con)

    job_id = collect_id = None
    fabric_result: Result = con.run(f'sh {submit_file}', hide=True)
    submit_stdout = fabric_result.stdout
    for line in submit_stdout.split("\n"):
        if line.startswith("Job id"):
            job_id = line.split()[-1]
        if line.startswith("Collect id"):
            collect_id = line.split()[-1]

    if job_id is None or collect_id is None:
        return {
            "message": "Job submission failed",
            "submit_stdout": submit_stdout,
            "sh_files": sh_files
        }
    return {
        "message": "Job submitted",
        "job_id": f"{utc_time}:{job_id}:{collect_id}:{cluster.cluster_name}",
        "submit_stdout": submit_stdout,
        "sh_files": sh_files
    }


def prepare_script_files(payload_dict: dict, job_dir: str, con: Connection) -> tuple[str, dict]:
    """Prepares script files to run them on cluster"""
    submit_file = f'{job_dir}/yaptide_submitter.sh'
    array_file = f'{job_dir}/array_script.sh'
    collect_file = f'{job_dir}/collect_script.sh'

    array_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="array_options")
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")

    collect_options = convert_dict_to_sbatch_options(payload_dict=payload_dict, target_key="collect_options")
    collect_header = extract_sbatch_header(payload_dict=payload_dict, target_key="collect_header")

    submit_script = SUBMIT_SHIELDHIT.format(
        array_options=array_options,
        collect_options=collect_options,
        root_dir=job_dir,
        n_tasks=str(payload_dict["ntasks"]),
        convertmc_version=pymchelper.__version__
    )
    array_script = ARRAY_SHIELDHIT_BASH.format(
        array_header=array_header,
        root_dir=job_dir
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


def get_job_status(concat_job_id: str, cluster: ClusterModel) -> dict:
    """Dummy version of get_job_status"""
    _, job_id, collect_id, _ = concat_job_id.split(":")
    pkey = Ed25519Key(file_obj=io.StringIO(cluster.cluster_ssh_key))
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )

    fabric_result: Result = con.run(f'sacct -j {job_id} --format State', hide=True)
    job_state = fabric_result.stdout.split()[-1].split()[0]

    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]

    if job_state == "FAILED" or collect_state == "FAILED":
        return {
            "job_state": SimulationModel.JobState.FAILED.value
        }
    if collect_state == "COMPLETED":
        return {
            "job_state": SimulationModel.JobState.COMPLETED.value,
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
        "job_state": SimulationModel.JobState.RUNNING.value
    }


def get_job_results(concat_job_id: str, cluster: ClusterModel) -> dict:
    """Returns simulation results"""
    utc_time, job_id, collect_id, _ = concat_job_id.split(":")
    pkey = Ed25519Key(file_obj=io.StringIO(cluster.cluster_ssh_key))
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )
    fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = fabric_result.stdout.split()[0]

    job_dir = f"{scratch}/yaptide_runs/{utc_time}"
    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]

    if collect_state == "COMPLETED":
        fabric_result: Result = con.run(f'ls -f {job_dir}/output | grep .json', hide=True)
        result_dict = {"estimators": []}
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            for filename in fabric_result.stdout.split():
                file_path = Path(tmp_dir_path, filename)
                with open(file_path, "wb") as writer:
                    con.get(f'{job_dir}/output/{filename}', writer)
                with open(file_path, "r") as json_file:
                    est_dict = json.load(json_file)
                    est_dict["name"] = filename.split('.')[0]
                    result_dict["estimators"].append(est_dict)

        return {
            "result": result_dict,
        }
    return {
        "message": "Results not available"
    }


def delete_job(concat_job_id: str, cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    return {"message": "Not implemented yet"}, 404
