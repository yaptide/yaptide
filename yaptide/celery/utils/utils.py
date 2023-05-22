import logging
import re
import time
import os

from datetime import datetime
from pathlib import Path

import requests

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


def get_job_status(job_id: str) -> dict:
    """
    Returns simulation state, results are not returned here
    Simulation may consist of multiple tasks, so we need to check all of them
    """
    # Here we ask Celery (via Redis) for job state
    job = AsyncResult(id=job_id, app=celery_app)
    job_state: str = translate_celery_state_naming(job.state)

    # we still need to convert string to enum and operate later on Enum
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
    else:
        result["message"] = str(job.info)

    return result


def get_job_results(job_id: str) -> dict:
    """Returns simulation results"""
    job = AsyncResult(id=job_id, app=celery_app)
    if "result" not in job.info:
        return {}
    return job.info.get("result")


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


def send_task_update(simulation_id: int, task_id: str, update_key: str, update_dict: dict) -> bool:
    """Sends task update to flask to update database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    res: requests.Response = requests.Session().post(url=f"{flask_url}/tasks/update", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Task update for %s - Failed: %s", task_id, res.json().get("message"))
        return False
    return True


def send_simulation_results(simulation_id: int, update_key: str, estimators: dict) -> bool:
    """Sends results of simulation to flask to save it in database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "estimators": estimators["estimators"],
    }
    logging.info("Sending results to flask via %s", flask_url)
    res: requests.Response = requests.Session().post(url=f"{flask_url}/results", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Saving results failed: %s", res.json().get("message"))
        return False
    return True


def send_simulation_logfiles(simulation_id: int, update_key: str, logfiles: dict) -> bool:
    """Sends results of simulation to flask to save it in database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "logfiles": logfiles,
    }
    logging.info("Sending log files to flask via %s", flask_url)
    res: requests.Response = requests.Session().post(url=f"{flask_url}/logfiles", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Saving logfiles failed: %s", res.json()["message"])
        return False
    return True


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
                "start_time": utc_now.isoformat(sep=" "),
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
