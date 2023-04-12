import io
import json
import tempfile

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
from yaptide.persistence.models import SimulationModel, ClusterModel
from yaptide.utils.sim_utils import write_input_files


def submit_job(json_data: dict, cluster: ClusterModel) -> tuple[dict, int]:  # skipcq: PYL-W0613
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

    con.run(f"mkdir -p {job_dir}")
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        zip_path = Path(tmp_dir_path) / "input.zip"
        write_input_files(json_data, Path(tmp_dir_path))
        with ZipFile(zip_path, mode="w") as archive:
            for file in Path(tmp_dir_path).iterdir():
                if file.name == "input.zip":
                    continue
                archive.write(file, arcname=file.name)
        con.put(zip_path, job_dir)

    WATCHER_SCRIPT = Path(__file__).parent.resolve() / "watcher.py"
    con.put(WATCHER_SCRIPT, job_dir)

    submit_file = f'{job_dir}/yaptide_submitter.sh'
    array_file = f'{job_dir}/array_script.sh'
    collect_file = f'{job_dir}/collect_script.sh'

    submit_script = SUBMIT_SHIELDHIT.format(
        root_dir=job_dir,
        n_tasks=str(3),
        convertmc_version=pymchelper.__version__
    )
    array_script = ARRAY_SHIELDHIT_BASH.format(
        root_dir=job_dir,
        particle_no=str(10000)
    )
    collect_script = COLLECT_BASH.format(
        root_dir=job_dir,
        clear_bdos="true"
    )

    con.run(f'echo \'{array_script}\' >> {array_file}')
    con.run(f'chmod +x {array_file}')
    con.run(f'echo \'{submit_script}\' >> {submit_file}')
    con.run(f'chmod +x {submit_file}')
    con.run(f'echo \'{collect_script}\' >> {collect_file}')
    con.run(f'chmod +x {collect_file}')

    fabric_result: Result = con.run(f'sh {submit_file}', hide=True)
    for line in fabric_result.stdout.split("\n"):
        if line.startswith("Job id"):
            job_id = line.split()[-1]
        if line.startswith("Collect id"):
            collect_id = line.split()[-1]

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
    fabric_result: Result = con.run("echo $SCRATCH", hide=True)
    scratch = fabric_result.stdout.split()[0]

    job_dir = f"{scratch}/yaptide_runs/{utc_time}"
    fabric_result: Result = con.run(f'sacct -j {job_id} --format State', hide=True)
    job_state = fabric_result.stdout.split()[-1].split()[0]
    fabric_result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = fabric_result.stdout.split()[-1].split()[0]
    if job_state == "PENDING":  # skipcq: PTC-W0047
        pass
    if collect_state == "FAILED":
        return {
            "job_state": SimulationModel.JobStatus.FAILED.value,
            "message": "Simulation FAILED"
        }
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
        now = datetime.utcnow()
        return {
            "job_state": SimulationModel.JobStatus.COMPLETED.value,
            "result": result_dict,
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
    if collect_state == "RUNNING":  # skipcq: PTC-W0047
        pass
    if job_state == "RUNNING":  # skipcq: PTC-W0047
        pass
    if collect_state == "PENDING":    # skipcq: PTC-W0047
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
