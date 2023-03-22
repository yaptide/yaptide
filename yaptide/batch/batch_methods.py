from fabric import Connection, Result
from paramiko import Ed25519Key

import json as json_lib
import io
import os
import sys
import tempfile

from datetime import datetime

from pathlib import Path

from pymchelper.input_output import fromfile

from yaptide.persistence.models import SimulationModel, ClusterModel

from yaptide.batch.string_templates import SUBMIT_SHIELDHIT, ARRAY_SHIELDHIT_BASH, COLLECT_BASH

from yaptide.celery.tasks import pymchelper_output_to_json

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append("yaptide/converter")
from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


def write_input_files(json_data: dict, output_dir: Path):
    """
    Function used to write input files to output directory.
    Returns dictionary with filenames as keys and their content as values
    """
    if "beam.dat" not in json_data["sim_data"]:
        conv_parser = get_parser_from_str(json_data["sim_type"])
        return run_parser(parser=conv_parser, input_data=json_data["sim_data"], output_dir=output_dir)

    for key, file in json_data["sim_data"].items():
        with open(Path(output_dir, key), "w") as writer:
            writer.write(file)
    return json_data["sim_data"]


def submit_job(json_data: dict, cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of submit_job"""
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        input_files = write_input_files(json_data, Path(tmp_dir_path))
    
    utc_time = int(datetime.utcnow().timestamp()*1e6)
    pkey = Ed25519Key(file_obj=io.StringIO(cluster.cluster_ssh_key))
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )

    result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = result.stdout.split()[0]

    job_dir=f"{scratch}/yaptide_runs/{utc_time}"

    con.run(f"mkdir -p {job_dir}")

    submit_file = f'{job_dir}/yaptide_submitter.sh'
    array_file = f'{job_dir}/array_script.sh'
    collect_file = f'{job_dir}/collect_script.sh'

    submit_script = SUBMIT_SHIELDHIT.format(
        root_dir=job_dir,
        beam=input_files["beam.dat"],
        detect=input_files["detect.dat"],
        geo=input_files["geo.dat"],
        mat=input_files["mat.dat"],
        n_tasks=str(1)
    )
    array_script = ARRAY_SHIELDHIT_BASH.format(
        root_dir=job_dir,
        particle_no=str(1000)
    )
    collect_script = COLLECT_BASH.format(
        root_dir=job_dir
    )

    con.run(f'echo \'{array_script}\' >> {array_file}')
    con.run(f'chmod 777 {array_file}')
    con.run(f'echo \'{submit_script}\' >> {submit_file}')
    con.run(f'chmod 777 {submit_file}')
    con.run(f'echo \'{collect_script}\' >> {collect_file}')
    con.run(f'chmod +x {collect_file}')

    result: Result = con.run(f'sh {submit_file}', hide=True)
    lines = result.stdout.split("\n")
    job_id = lines[0].split()[-1]
    collect_id = lines[1].split()[-1]

    return {
        "message": "Job submitted",
        "job_id": f"{utc_time}:{job_id}:{collect_id}:{cluster.cluster_name}"
    }, 202


def get_job(json_data: dict, cluster: ClusterModel) -> tuple[dict, int]:
    """Dummy version of get_job"""
    utc_time = json_data["utc_time"]
    job_id = json_data["job_id"]
    collect_id = json_data["collect_id"]
    pkey = Ed25519Key(file_obj=io.StringIO(cluster.cluster_ssh_key))
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )
    result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = result.stdout.split()[0]

    job_dir=f"{scratch}/yaptide_runs/{utc_time}"
    result: Result = con.run(f'sacct -j {job_id} --format State', hide=True)
    job_state = result.stdout.split()[-1].split()[0]
    result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = result.stdout.split()[-1].split()[0]
    if job_state == "PENDING":  # PENDING
        pass
    if collect_state == "FAILED":  # FAILED
        return {
            "job_state": SimulationModel.JobStatus.FAILED.value,
            "message": "Simulation FAILED"
        }
    if collect_state == "COMPLETED":  # COMPLETED
        pass
        result: Result = con.run(f'ls -f {job_dir}/output | grep .bdo', hide = True)
        estimators_dict = {}
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            for filename in result.stdout.split():
                file_path = Path(tmp_dir_path, filename)
                with open(file_path, "wb") as writer:
                    con.get(f'{job_dir}/output/{filename}', writer)
                estimators_dict[filename.split('.')[0]] = fromfile(str(file_path))
        result = pymchelper_output_to_json(estimators_dict=estimators_dict)
        now = datetime.utcnow()
        return {
            "job_state": SimulationModel.JobStatus.COMPLETED.value,
            "result": result,
            "end_time": now,
            "job_tasks_status": [
                {
                    "task_id": 1,
                    "task_state": SimulationModel.JobStatus.COMPLETED.value,
                    "simulated_primaries": 2000,
                    "requested_primaries": 2000,
                    "run_time": {
                        "hours": 0,
                        "minutes": 0,
                        "seconds": 45,
                    }
                }
            ]
        }, 200
    if collect_state == "RUNNING":  # RUNNING
        pass
    if job_state == "RUNNING":  # RUNNING
        pass
    if collect_state == "PENDING":  # RUNNING
        pass

    return {
        "job_state": SimulationModel.JobStatus.RUNNING.value,
        "job_tasks_status": [
            {
                "task_id": 1,
                "task_state": SimulationModel.JobStatus.RUNNING.value,
                "simulated_primaries": 1000,
                "requested_primaries": 2000,
                "estimated_time": {
                    "hours": 0,
                    "minutes": 0,
                    "seconds": 30,
                }
            }
        ]
    }, 200


def delete_job(json_data: dict, cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    return {"message": "Not implemented yet"}, 404
