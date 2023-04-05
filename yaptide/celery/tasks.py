import re
import tempfile
import time

from pathlib import Path
from datetime import datetime

from multiprocessing import Lock, Process
from multiprocessing.managers import BaseManager

from celery.result import AsyncResult

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner

from yaptide.batch.watcher import (
    log_generator,
    RUN_MATCH,
    COMPLETE_MATCH,
    REQUESTED_MATCH,
    TIMEOUT_MATCH
)
from yaptide.celery.worker import celery_app
from yaptide.persistence.models import SimulationModel
from yaptide.utils.sim_utils import (
    pymchelper_output_to_json,
    write_input_files,
    simulation_logfiles,
    simulation_input_files
)


class SimulationStats():
    """Class holding simulation statistics"""

    def __init__(self, ntasks: int, parent, parent_id: str):
        self.lock = Lock()
        self.tasks_status = {}
        self.parent = parent
        self.parent_id = parent_id
        for i in range(ntasks):
            self.tasks_status[str(i+1)] = {
                "task_id": i+1,
                "task_state": SimulationModel.JobStatus.PENDING.value
            }
        parent_state = AsyncResult(parent_id).state
        parent_meta = AsyncResult(parent_id).info
        parent_meta["job_tasks_status"] = self.to_list()
        self.parent.update_state(task_id=self.parent_id, state=parent_state, meta=parent_meta)

    def update(self, task_id: str, up_dict: dict, final: bool = False):
        """Method updating simulation statistics"""
        self.lock.acquire()
        try:
            for key, value in up_dict.items():
                self.tasks_status[task_id][key] = value
            if final:
                self.tasks_status[task_id]["simulated_primaries"] = self.tasks_status[task_id]["requested_primaries"]
                self.tasks_status[task_id].pop("estimated_time", None)
            parent_state = AsyncResult(self.parent_id).state
            parent_meta = AsyncResult(self.parent_id).info
            parent_meta["job_tasks_status"] = self.to_list()
            self.parent.update_state(task_id=self.parent_id, state=parent_state, meta=parent_meta)
        finally:
            self.lock.release()

    def to_list(self) -> list:
        """To list"""
        return [value for _, value in self.tasks_status.items()]


class SharedResourcesManager(BaseManager):
    """Shared objects manager for multiprocessing"""


def read_file(stats: SimulationStats, filepath: Path, task_id: int):
    """Monitors log file of certain task"""
    logfile = None
    for _ in range(30):  # 30 stands for maximum attempts
        try:
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    if logfile is None:
        up_dict = {
            "task_state": SimulationModel.JobStatus.FAILED.value
        }
        stats.update(str(task_id), up_dict)

    loglines = log_generator(logfile)
    for line in loglines:
        if re.search(RUN_MATCH, line):
            splitted = line.split()
            up_dict = {
                "simulated_primaries": int(splitted[3]),
                "estimated_time": {
                    "hours": int(splitted[5]),
                    "minutes": int(splitted[7]),
                    "seconds": int(splitted[9]),
                }
            }
            stats.update(str(task_id), up_dict)

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": SimulationModel.JobStatus.RUNNING.value
            }
            stats.update(str(task_id), up_dict)

        elif re.search(COMPLETE_MATCH, line):
            splitted = line.split()
            up_dict = {
                "run_time": {
                    "hours": int(splitted[2]),
                    "minutes": int(splitted[4]),
                    "seconds": int(splitted[6]),
                },
                "task_state": SimulationModel.JobStatus.COMPLETED.value
            }
            stats.update(str(task_id), up_dict, True)
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {
                "task_state": SimulationModel.JobStatus.FAILED.value
            }
            stats.update(str(task_id), up_dict)
            return


@celery_app.task(bind=True)
def run_simulation(self, json_data: dict):
    """Simulation runner"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        input_files = write_input_files(json_data, Path(tmp_dir_path))
        # we assume here that the simulation executable is available in the PATH so pymchelper will discover it
        settings = SimulationSettings(input_path=tmp_dir_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts="")

        ntasks = json_data["ntasks"] if json_data["ntasks"] > 0 else None

        runner_obj = SHRunner(jobs=ntasks,
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)
        ntasks = runner_obj.jobs

        logs_list = [Path(tmp_dir_path) / f"run_{1+i}" / f"shieldhit_{1+i:04d}.log" for i in range(ntasks)]

        self.update_state(state="PROGRESS", meta={"path": tmp_dir_path, "sim_type": json_data["sim_type"]})

        SharedResourcesManager.register('SimulationStats', SimulationStats)
        with SharedResourcesManager() as manager:
            stats: SimulationStats = manager.SimulationStats(ntasks, self, self.request.id)
            monitoring_processes = [Process(target=read_file, args=(stats, logs_list[i], i+1)) for i in range(ntasks)]
            for process in monitoring_processes:
                process.start()

            try:
                is_run_ok = runner_obj.run(settings=settings)
                if not is_run_ok:
                    raise Exception
            except Exception:  # skipcq: PYL-W0703
                logfiles = simulation_logfiles(path=Path(tmp_dir_path))
                input_files = simulation_input_files(path=Path(tmp_dir_path))
                return {"logfiles": logfiles, "input_files": input_files}

            for process in monitoring_processes:
                process.join()

            final_stats = stats.to_list()

            estimators_dict: dict = runner_obj.get_data()

            result: dict = pymchelper_output_to_json(estimators_dict)

            return {
                "result": result,
                "input_json": json_data["sim_data"] if "metadata" in json_data["sim_data"] else None,
                "input_files": input_files,
                "end_time": datetime.utcnow(),
                "job_tasks_status": final_stats
            }


@celery_app.task
def convert_input_files(json_data: dict):
    """Function converting output"""
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        input_files = write_input_files(json_data, Path(tmp_dir_path))
        return {"input_files": input_files}


@celery_app.task
def simulation_task_status(job_id: str) -> dict:
    """Task responsible for returning simulation status"""
    job = AsyncResult(id=job_id, app=celery_app)
    job_state = job.state
    result = {
        "job_state": translate_celery_state_naming(job_state)
    }
    if job_state == "PENDING":
        pass
    elif job_state == "PROGRESS":
        if not job.info.get("sim_type") in {"shieldhit", "sh_dummy"}:
            return result
        result["job_tasks_status"] = job.info.get("job_tasks_status")
    elif job_state != "FAILURE":
        if "result" in job.info:
            for key in ["result", "input_files", "input_json", "end_time", "job_tasks_status"]:
                result[key] = job.info[key]
        elif "logfile" in job.info:
            result["job_state"] = translate_celery_state_naming("FAILURE")
            result["error"] = "Simulation error"
            result["logfiles"] = job.info.get("logfiles")
            result["input_files"] = job.info.get("input_files")
    else:
        result["error"] = str(job.info)

    return result


@celery_app.task
def get_input_files(job_id: str) -> dict:
    """Task responsible for returning simulation input files generated by converter"""
    job = AsyncResult(id=job_id, app=celery_app)

    if job.state == "PROGRESS":
        result = {"info": "Input files"}
        input_files = simulation_input_files(job.info.get("path"))
        for key, value in input_files.items():
            result[key] = value
        return result
    return {"info": "No input present"}


@celery_app.task
def cancel_simulation(job_id: str) -> bool:
    """Task responsible for canceling simulation in progress"""
    # Currently this task does nothing because to working properly it requires changes in pymchelper
    print(job_id)
    return False


def translate_celery_state_naming(job_state: str) -> str:
    """Function translating celery states' names to ones used in YAPTIDE"""
    if job_state in ["RECEIVED", "RETRY"]:
        return SimulationModel.JobStatus.PENDING.value
    if job_state in ["PROGRESS", "STARTED"]:
        return SimulationModel.JobStatus.RUNNING.value
    if job_state in ["FAILURE", "REVOKED"]:
        return SimulationModel.JobStatus.FAILED.value
    if job_state in ["SUCCESS"]:
        return SimulationModel.JobStatus.COMPLETED.value
    # Others are the same
    return job_state
