import logging
import os
import re
import subprocess
import time

from datetime import datetime
from pathlib import Path

from pymchelper.executor.options import SimulationSettings
from pymchelper.input_output import frompattern

from yaptide.batch.watcher import (
    log_generator,
    RUN_MATCH,
    COMPLETE_MATCH,
    REQUESTED_MATCH,
    TIMEOUT_MATCH
)
from yaptide.celery.utils.requests import send_task_update

from yaptide.utils.enums import EntityState


def run_shieldhit(dir_path: Path, task_id: str) -> dict:
    """Function run in eventlet to run single SHIELDHIT simulation"""
    settings = SimulationSettings(input_path=dir_path,  # skipcq: PYL-W0612 # usefull
                                  simulator_exec_path=None,  # useless
                                  cmdline_opts="")  # useless
    settings.set_rng_seed(int(task_id.split("_")[-1]))
    try:
        command_as_list = str(settings).split()
        command_as_list.append(str(dir_path))
        DEVNULL = open(os.devnull, 'wb')
        subprocess.check_call(command_as_list, cwd=str(dir_path), stdout=DEVNULL, stderr=DEVNULL)
        logging.info("SHIELDHIT simulation for task %s finished", task_id)

        estimators_dict = {}
        files_pattern_pattern = str(dir_path / "*.bdo")
        estimators_list = frompattern(files_pattern_pattern)
        for estimator in estimators_list:
            logging.debug("Appending estimator for {:s}".format(estimator.file_corename))
            estimators_dict[estimator.file_corename] = estimator

        return estimators_dict
    except Exception as e:  # skipcq: PYL-W0703
        logging.error("Exception while running SHIELDHIT: %s", e)

    # return empty dict if simulation failed
    return {}


def average_estimators(base_list: list[dict], list_to_add: list[dict], averaged_count: int) -> list:
    """Averages estimators from two dicts"""
    logging.debug("Averaging estimators - already averaged: %d", averaged_count)
    for est_i, estimator_dict in enumerate(list_to_add):
        # check if estimator names are the same and if not, find matching estimator's index in base_list
        if estimator_dict["name"] != base_list[est_i]["name"]:
            est_i = next((i for i, item in enumerate(base_list) if item["name"] == estimator_dict["name"]), None)
        logging.debug("Averaging estimator %s", estimator_dict["name"])
        for page_i, page_dict in enumerate(estimator_dict["pages"]):
            # check if page numbers are the same and if not, find matching page's index in base_list
            if page_dict["metadata"]["page_number"] != base_list[est_i]["pages"][page_i]["metadata"]["page_number"]:
                page_i = next((i for i, item in enumerate(base_list[est_i]["pages"])
                               if item["metadata"]["page_number"] == page_dict["metadata"]["page_number"]), None)

            base_list[est_i]["pages"][page_i]["data"]["values"] = [
                sum(x) / (averaged_count + 1) for x in zip(
                    map(lambda x: x * averaged_count, base_list[est_i]["pages"][page_i]["data"]["values"]),
                    page_dict["data"]["values"]
                )
            ]
            logging.debug("Averaged page %s with %d elements",
                          page_dict["metadata"]["page_number"],
                          len(page_dict["data"]["values"]))
    return base_list


def read_file(filepath: Path, simulation_id: int, task_id: str, update_key: str):
    """Monitors log file of certain task"""
    logging.getLogger(__name__).setLevel(logging.WARNING)
    logfile = None
    update_time = 0
    for _ in range(30):  # 30 stands for maximum attempts
        try:
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    if logfile is None:
        logging.error("Log file for task %s not found", task_id)
        up_dict = {
            "task_state": EntityState.FAILED.value
        }
        send_task_update(simulation_id, task_id, update_key, up_dict)
        return

    loglines = log_generator(logfile, timeout=30)
    requested_primaries = 0
    logging.info("Parsing log file for task %s started", task_id)
    for line in loglines:
        utc_now = datetime.utcnow()
        if re.search(RUN_MATCH, line):
            splitted = line.split()
            simulated_primaries = int(splitted[3])
            if (utc_now.timestamp() - update_time < 2  # hardcoded 2 seconds to avoid spamming
                    and requested_primaries > simulated_primaries):
                continue
            update_time = utc_now.timestamp()
            up_dict = {
                "simulated_primaries": simulated_primaries,
                "estimated_time": int(splitted[9])
                + int(splitted[7]) * 60
                + int(splitted[5]) * 3600
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            requested_primaries = int(splitted[1])
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": requested_primaries,
                "start_time": utc_now.isoformat(sep=" "),
                "task_state": EntityState.RUNNING.value
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(TIMEOUT_MATCH, line):
            logging.error("Simulation watcher %s timed out", task_id)
            up_dict = {
                "task_state": EntityState.FAILED.value
            }
            send_task_update(simulation_id, task_id, update_key, up_dict)
            return

        elif re.search(COMPLETE_MATCH, line):
            break

    up_dict = {
        "simulated_primaries": requested_primaries,
        "end_time": utc_now.isoformat(sep=" "),
        "task_state": EntityState.COMPLETED.value
    }
    send_task_update(simulation_id, task_id, update_key, up_dict)
