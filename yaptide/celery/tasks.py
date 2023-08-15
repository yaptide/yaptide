import contextlib
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import eventlet

from yaptide.admin.simulators import SimulatorType, install_simulator
from yaptide.celery.utils.pymc import (average_estimators, read_file,
                                       run_shieldhit)
from yaptide.celery.utils.requests import (send_simulation_logfiles,
                                           send_simulation_results,
                                           send_task_update)
from yaptide.celery.worker import celery_app
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import (check_and_convert_payload_to_files_dict,
                                     estimators_to_list, simulation_logfiles,
                                     write_simulation_input_files)

# this is not being used now but we can use such hook to install simulations on the worker start
# needs from celery.signals import worker_ready
# @worker_ready.connect
# def on_worker_ready(**kwargs):
#     """This function will be called when celery worker is ready to accept tasks"""
#     logging.info("on_worker_ready signal received")
#     # ask celery to install simulator on the worker and wait for it to finish
#     job = install_simulators.delay()
#     # we need to do some hackery here to make blocking calls work
#     # method described in https://stackoverflow.com/questions/33280456 doesn't work.
#     try:
#         job.wait()
#     except RuntimeError as e:
#         logging.info("the only way for blocking calls to work is to catch RuntimeError %s", e)
#         raise e


@celery_app.task()
def install_simulators() -> bool:
    """Task responsible for installing simulators on the worker"""
    result = install_simulator(SimulatorType.shieldhit)
    return result


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task(bind=True)
def run_single_simulation(self,
                          files_dict: dict,
                          task_id: str,
                          update_key: str = None,
                          simulation_id: int = None,
                          keep_tmp_files: bool = False) -> dict:
    """Function running single shieldhit simulation"""
    # for the purpose of running this function in pytest we would like to have some control
    # on the temporary directory used by the function

    logging.info("Running simulation, simulation_id: %s, task_id: %s", simulation_id, task_id)

    # lets try by default to use python tempfile module
    tmp_dir = tempfile.gettempdir()
    logging.debug("1. tempfile.gettempdir() is: %s", tmp_dir)

    # if the TMPDIR env variable is set we will use it to override the default
    logging.info("1. TMPDIR is: %s", os.environ.get("TMPDIR", "not set"))
    if os.environ.get("TMPDIR"):
        tmp_dir = os.environ.get("TMPDIR")

    # if the TEMP env variable is set we will use it to override the default
    logging.info("2. TEMP is: %s", os.environ.get("TEMP", "not set"))
    if os.environ.get("TEMP"):
        tmp_dir = os.environ.get("TEMP")

    # if the TMP env variable is set we will use it to override the default
    logging.info("3. TMP is: %s", os.environ.get("TMP", "not set"))
    if os.environ.get("TMP"):
        tmp_dir = os.environ.get("TMP")

    # with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp_dir_path:
    # use the selected temporary directory to create a temporary directory
    with (
        contextlib.nullcontext(tempfile.mkdtemp(dir=tmp_dir))
        if keep_tmp_files
        else tempfile.TemporaryDirectory(dir=tmp_dir)
    ) as tmp_dir_path:
        logging.debug("Task %s saves the files for simulation %s", task_id, files_dict.keys())
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))

        watcher_green_thread = None
        # we would like to monitor the progress of simulation
        # this is done by reading the log file and sending the updates to the backend
        # if we have update_key and simulation_id the monitoring thread can submit the updates to backend
        if update_key is not None and simulation_id is not None:

            logging.info("Sending update for task %s, setting celery id %s", task_id, self.request.id)
            send_task_update(simulation_id, task_id, update_key, {"celery_id": self.request.id})

            path_to_monitor = Path(tmp_dir_path) / f"shieldhit_{int(task_id.split('_')[-1]):04d}.log"

            current_logging_level = logging.getLogger().getEffectiveLevel()

            watcher_green_thread = eventlet.spawn(read_file,
                                                  path_to_monitor,
                                                  simulation_id,
                                                  task_id,
                                                  update_key,
                                                  current_logging_level)
            logging.info("Started monitoring process for task %s", task_id)
        else:
            logging.info("No monitoring processes started for task %s", task_id)

        logging.info("Running SHIELDHIT simulation in %s", tmp_dir_path)
        estimators_dict = run_shieldhit(dir_path=Path(tmp_dir_path), task_id=task_id)
        logging.info("Simulation finished for task %s", task_id)

        # at this point simulation is finished (failed or succeded) and we can kill the monitoring process
        if watcher_green_thread is not None:
            logging.info("Killing monitoring processes for task %s", task_id)
            watcher_green_thread.kill()
        else:
            logging.info("No monitoring processes to kill for task %s", task_id)

        # here we have simulation which failed, this means we mark the task as failed
        if not estimators_dict:
            logging.info("Simulation failed for task %s, sending update that it has failed", task_id)
            send_task_update(simulation_id, task_id, update_key, {"task_state": "FAILED"})

            logfiles = simulation_logfiles(path=Path(tmp_dir_path))
            logging.info("Simulation failed, logfiles: %s", logfiles.keys())
            if send_simulation_logfiles(simulation_id=simulation_id,
                                        update_key=update_key,
                                        logfiles=logfiles):
                return {}
            return {
                "logfiles": logfiles,
                "simulation_id": simulation_id,
                "update_key": update_key
            }

        logging.debug("Converting simulation results to JSON")
        estimators = estimators_to_list(estimators_dict=estimators_dict,
                                        dir_path=Path(tmp_dir_path))

        end_time = datetime.utcnow().isoformat(sep=" ")

        # We do not have any information if monitoring process sent the last update
        # so we send it here to make sure that we have the end_time and COMPLETED state
        update_dict = {"task_state": EntityState.COMPLETED.value, "end_time": end_time}
        send_task_update(simulation_id, task_id, update_key, update_dict)

        return {
            "estimators": estimators,
            "simulation_id": simulation_id,
            "update_key": update_key
        }


@celery_app.task
def merge_results(results: list[dict]) -> dict:
    """Merge results from multiple simulation's tasks"""
    logging.debug("Merging results from %d tasks", len(results))
    logfiles = {}

    averaged_estimators = None
    simulation_id = results[0].pop("simulation_id", None)
    update_key = results[0].pop("simulation_id", None)
    for i, result in enumerate(results):
        if simulation_id is None:
            simulation_id = result.pop("simulation_id", None)
        if update_key is None:
            update_key = result.pop("update_key", None)
        if "logfiles" in result:
            logfiles.update(result["logfiles"])
            continue

        if averaged_estimators is None:
            averaged_estimators: list[dict] = result.get("estimators", [])
            # There is nothing to average yet
            continue

        averaged_estimators = average_estimators(averaged_estimators, result.get("estimators", []), i)

    final_result = {
        "end_time": datetime.utcnow().isoformat(sep=" ")
    }

    if len(logfiles.keys()) > 0 and not send_simulation_logfiles(simulation_id=simulation_id,
                                                                 update_key=update_key,
                                                                 logfiles=logfiles):
        final_result["logfiles"] = logfiles

    if averaged_estimators is not None and not send_simulation_results(simulation_id=simulation_id,
                                                                       update_key=update_key,
                                                                       estimators=averaged_estimators):
        final_result["estimators"] = averaged_estimators

    return final_result
