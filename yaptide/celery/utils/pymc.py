import logging
import os
import re
import subprocess
import time

from datetime import datetime
from pathlib import Path

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner

from yaptide.batch.watcher import (
    log_generator,
    RUN_MATCH,
    COMPLETE_MATCH,
    REQUESTED_MATCH,
    TIMEOUT_MATCH
)
from yaptide.celery.utils.requests import send_task_update

from yaptide.persistence.models import SimulationModel


def run_shieldhit(dir_path: Path, task_id: int) -> dict:
    """Function run in eventlet to run single SHIELDHIT simulation"""
    logging.info("Running SHIELDHIT simulation in %s", dir_path)
    runner_obj = SHRunner(jobs=1,  # useless
                          keep_workspace_after_run=True,  # useless
                          output_directory=dir_path)  # usefull

    settings = SimulationSettings(input_path=dir_path,  # skipcq: PYL-W0612 # usefull
                                  simulator_exec_path=None,  # useless
                                  cmdline_opts="")  # useless
    settings.set_rng_seed(task_id)
    try:
        command_as_list = str(settings).split()
        command_as_list.append(str(dir_path))
        DEVNULL = open(os.devnull, 'wb')
        subprocess.check_call(command_as_list, cwd=str(dir_path), stdout=DEVNULL, stderr=DEVNULL)
        # is_run_ok = runner_obj.run(settings=settings)
        # if is_run_ok:
        #     return runner_obj.get_data()
    except Exception as e:  # skipcq: PYL-W0703
        logging.error("Exception while running SHIELDHIT: %s", e)

    # return empty dict if simulation failed
    return {}


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
