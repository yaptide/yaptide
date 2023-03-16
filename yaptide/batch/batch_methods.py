from fabric import Connection, Result
from paramiko import Ed25519Key

import json as json_lib
import os
import sys
import tempfile

import time
from datetime import datetime

from pathlib import Path

from yaptide.persistence.models import SimulationModel, ClusterModel

from yaptide.batch.string_templates import SHIELDHIT_BASH

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
        script = SHIELDHIT_BASH.format(
            beam=input_files["beam.dat"],
            detect=input_files["detect.dat"],
            geo=input_files["geo.dat"],
            mat=input_files["mat.dat"]
        )
        ssh_key_path = Path(tmp_dir_path, "id_ed25519")
        with open(ssh_key_path, "w") as writer:
            writer.write(cluster.cluster_ssh_key)
        pkey = Ed25519Key(filename=ssh_key_path)
    con = Connection(
        host=f"{cluster.cluster_username}@{cluster.cluster_name}",
        connect_kwargs={"pkey": pkey}
    )
    con.run(f'echo \'{script}\' >> yaptide_script.sh')
    con.run('chmod 777 yaptide_script.sh')

    result: Result = con.run('sbatch new_script.sh')

    job_id = int(result.stdout.split()[3])

    return {
        "message": "Dummy submit",
        "job_id": f"{job_id}:{cluster.cluster_name}"
    }, 202


def get_job(json_data: dict) -> tuple[dict, int]:
    """Dummy version of get_job"""
    now = datetime.utcnow()
    time_diff = now - json_data["start_time_for_dummy"]
    if time_diff.seconds < 30 and json_data["end_time_for_dummy"] is None:
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
                        "seconds": 30 - time_diff.seconds,
                    }
                }
            ]
        }, 200

    with open(Path(ROOT_DIR, "dummy_output.json")) as json_file:
        result = json_lib.load(json_file)
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
                    "seconds": 30,
                }
            }
        ]
    }, 200


def delete_job(json_data: dict) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    return {"message": "Not implemented yet"}, 404


def fetch_bdo_files(json_data: dict) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of fetch_bdo_files"""
    return {"message": "Not implemented yet"}, 404
