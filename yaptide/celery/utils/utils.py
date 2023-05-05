import logging
import re
import time
import os

from datetime import datetime
from pathlib import Path

import requests

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
    job_state: str = translate_celery_state_naming(job.state)

    # we still need to  convert string to enum and operate later on Enum
    result = {
        "job_state": job_state
    }
    if job_state == SimulationModel.JobState.PENDING.value:
        pass
    elif job_state == SimulationModel.JobState.RUNNING.value:
        pass
    elif job_state != SimulationModel.JobState.FAILED.value:
        if "end_time" in job.info:
            result["end_time"] = job.info["end_time"]
        elif "logfile" in job.info:
            result["job_state"] = SimulationModel.JobState.FAILED.value
            result["error"] = "Simulation error"
            result["logfiles"] = job.info.get("logfiles")
            result["input_files"] = job.info.get("input_files")
    else:
        result["error"] = str(job.info)

    return result


def get_job_results(job_id: str) -> dict:
    """Returns simulation results"""
    job = AsyncResult(id=job_id, app=celery_app)
    result = {}
    if "result" in job.info:
        result = {
            "result": job.info("result"),
            "input_files": job.info("input_files"),
            "input_json": job.info("input_json")
        }
    return result


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


def read_file_old(stats: SimulationStats, filepath: Path, task_id: int):
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


def send_task_update(simulation_id: int, task_id: str, update_key: str, update_dict: dict):
    """Sends task update to database"""
    flask_url = os.environ.get("FLASK_INTERNAL_URL")
    if not flask_url:
        logging.debug("Flask url not found")
        return
    dict_to_send = {
        "simulation_id": simulation_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    res: requests.Response = requests.Session().post(url=f"{flask_url}/tasks/update", json=dict_to_send)
    if res.status_code != 202:
        logging.debug("Task update for %s - Failed: %s", task_id, res.json().get("message"))


def read_file(filepath: Path, simulation_id: int, task_id: str, update_key: str):
    """Monitors log file of certain task"""
    logfile = None
    update_time = 0
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
        send_task_update(simulation_id, task_id, update_key, up_dict)

    loglines = log_generator(logfile)
    for line in loglines:
        utc_now = datetime.utcnow()
        if re.search(RUN_MATCH, line):
            if utc_now.timestamp() - update_time < 2:  # hardcoded 2 seconds to avoid spamming
                continue
            update_time = utc_now.timestamp()
            splitted = line.split()
            up_dict = {
                "simulated_primaries": int(splitted[3]),
                "estimated_time": int(splitted[9])
                + int(splitted[7]) * 60
                + int(splitted[5]) * 3600
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": SimulationModel.JobState.RUNNING.value
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(COMPLETE_MATCH, line):
            splitted = line.split()
            up_dict = {
                "end_time": utc_now.isoformat(sep=" "),
                "task_state": SimulationModel.JobState.COMPLETED.value
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {
                "task_state": SimulationModel.JobState.FAILED.value
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)
            return
