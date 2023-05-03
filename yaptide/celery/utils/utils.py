import logging
import re
import time

from datetime import datetime
from pathlib import Path

from multiprocessing import Lock
from multiprocessing.managers import BaseManager

from celery.result import AsyncResult

from yaptide.celery.worker import celery_app
from yaptide.batch.watcher import (
    log_generator,
    RUN_MATCH,
    COMPLETE_MATCH,
    REQUESTED_MATCH,
    TIMEOUT_MATCH
)
from yaptide.persistence.models import SimulationModel


def get_job_status_as_dict(job_id: str) -> dict:
    """
    Returns simulation state, results are not returned here
    Simulation may consist of multiple tasks, so we need to check all of them
    """
    # Here we ask Celery (via Redis) for job state
    job = AsyncResult(id=job_id, app=celery_app)
    job_state: str = job.state

    # TODO convert string to enum and operate later on Enum
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


def get_job_results(job_id: str) -> dict:
    """Returns simulation results"""
    job = AsyncResult(id=job_id, app=celery_app)
    if "result" in job.info:
        return {
            "result": job.info("result"),
            "input_files": job.info("input_files"),
            "input_json": job.info("input_json"),
            "result": job.info("result")
        }


def translate_celery_state_naming(job_state: str) -> str:
    """Function translating celery states' names to ones used in YAPTIDE"""
    if job_state in ["RECEIVED", "RETRY"]:
        return SimulationModel.JobState.PENDING.value
    if job_state in ["PROGRESS", "STARTED"]:
        return SimulationModel.JobState.RUNNING.value
    if job_state in ["FAILURE", "REVOKED"]:
        return SimulationModel.JobState.FAILED.value
    if job_state in ["SUCCESS"]:
        return SimulationModel.JobState.COMPLETED.value
    # Others are the same
    return job_state


class SimulationStats():
    """Class holding simulation statistics"""

    def __init__(self, ntasks: int, parent, parent_id: str):
        logging.debug("Initializing SimulationStats")
        self.lock = Lock()
        logging.debug("SimulationStats lock acquired")
        self.tasks_status: dict = {}
        self.parent = parent
        self.parent_id = parent_id
        logging.debug("parent id: %s", parent_id)
        for i in range(ntasks):
            self.tasks_status[str(i+1)] = {
                "task_id": i+1,
                "task_state": SimulationModel.JobState.PENDING.value
            }
        parent_state = AsyncResult(parent_id).state
        parent_meta = AsyncResult(parent_id).info
        if parent_meta:
            parent_meta["job_tasks_status"] = list(self.tasks_status.values())
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
            parent_meta["job_tasks_status"] = list(self.tasks_status.values())
            # update parent state (parent.info)
            self.parent.update_state(task_id=self.parent_id, state=parent_state, meta=parent_meta)
        finally:
            self.lock.release()


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
            "task_state": SimulationModel.JobState.FAILED.value
        }
        stats.update(str(task_id), up_dict)

    loglines = log_generator(logfile)
    for line in loglines:
        if re.search(RUN_MATCH, line):
            splitted = line.split()
            up_dict = {
                "simulated_primaries": int(splitted[3]),
                "estimated_time": int(splitted[9])
                + int(splitted[7]) * 60
                + int(splitted[5]) * 3600
            }

            stats.update(str(task_id), up_dict)

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": SimulationModel.JobState.RUNNING.value
            }
            stats.update(str(task_id), up_dict)

        elif re.search(COMPLETE_MATCH, line):
            splitted = line.split()
            up_dict = {
                "end_time": datetime.utcnow(),
                "task_state": SimulationModel.JobState.COMPLETED.value
            }
            stats.update(str(task_id), up_dict, True)
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {
                "task_state": SimulationModel.JobState.FAILED.value
            }
            stats.update(str(task_id), up_dict)
            return
