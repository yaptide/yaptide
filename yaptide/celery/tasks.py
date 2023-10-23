from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import contextlib
import logging
import multiprocessing
import os
import tempfile
from datetime import datetime
from pathlib import Path
import time

from yaptide.admin.simulators import SimulatorType, install_simulator
from yaptide.celery.utils.pymc import (average_estimators, command_to_run_shieldhit, execute_shieldhit_process, get_shieldhit_estimators, read_file)
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
    result = install_simulator(SimulatorType.shieldhit, Path('/simulators/shieldhit12a/bin'))
    return result


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


def get_tmp_dir() -> Path:
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

    return Path(tmp_dir)


@celery_app.task(bind=True)
def run_single_simulation(self,
                          files_dict: dict,
                          task_id: str,
                          update_key: str = '',
                          simulation_id: int = None,
                          keep_tmp_files: bool = False) -> dict:
    """Function running single shieldhit simulation"""
    # for the purpose of running this function in pytest we would like to have some control
    # on the temporary directory used by the function

    logging.info("Running simulation, simulation_id: %s, task_id: %s", simulation_id, task_id)

    logging.info("Sending initial update for task %s, setting celery id %s", task_id, self.request.id)
    send_task_update(simulation_id, task_id, update_key, {"celery_id": self.request.id})

    # we would like to have some control on the temporary directory used by the function
    tmp_dir = get_tmp_dir()
    logging.info("Temporary directory is: %s", tmp_dir)

    command_stdout, command_stderr = '', ''

    # with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp_dir_path:
    # use the selected temporary directory to create a temporary directory
    with (
        contextlib.nullcontext(tempfile.mkdtemp(dir=tmp_dir))
        if keep_tmp_files
        else tempfile.TemporaryDirectory(dir=tmp_dir)
    ) as tmp_work_dir:
        
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_work_dir))
        logging.debug("Generated input files: %s", files_dict.keys())

        command_as_list = command_to_run_shieldhit(dir_path = Path(tmp_work_dir), task_id = task_id)
        logging.info("Command to run SHIELD-HIT12A: %s", " ".join(command_as_list))

        # we would like to monitor the progress of simulation
        # this is done by reading the log file and sending the updates to the backend
        # if we have update_key and simulation_id the monitoring task can submit the updates to backend
        if update_key and simulation_id is not None:

            path_to_monitor = Path(tmp_work_dir) / f"shieldhit_{int(task_id.split('_')[-1]):04d}.log"
            current_logging_level = logging.getLogger().getEffectiveLevel()

            background_process = multiprocessing.Process(
                target=read_file,
                args=(path_to_monitor, simulation_id, task_id, update_key, current_logging_level)
            )
            background_process.start()
            logging.info("Started monitoring process for task %s", task_id)
        else:
            logging.info("No monitoring processes started for task %s", task_id)

        # while monitoring process is active we can run the SHIELD-HIT12A process
        logging.info("Running SHIELD-HIT12A process in %s", tmp_work_dir)
        process_exit_success, command_stdout, command_stderr = execute_shieldhit_process(dir_path=Path(tmp_work_dir),command_as_list=command_as_list)
        time.sleep(5)
        logging.info("SHIELD-HIT12A process finished with status %s", process_exit_success)

        # terminate monitoring process
        if update_key and simulation_id is not None:
            background_process.terminate()
            background_process.join()

        # both simulation execution and monitoring process are finished now, we can read the estimators
        estimators_dict = get_shieldhit_estimators(dir_path=Path(tmp_work_dir))

        # there is no simulation output
        if not estimators_dict:

            # first we notify the backend that the task with simulation has failed
            logging.info("Simulation failed for task %s, sending update that it has failed", task_id)
            update_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
            send_task_update(simulation_id, task_id, update_key, update_dict)

            # then we send the logfiles to the backend, if available
            logfiles = simulation_logfiles(path=Path(tmp_work_dir))
            logging.info("Simulation failed, logfiles: %s", logfiles.keys())
            if logfiles:
                pass
                # the method below is in particular broken, as there may be several logfiles, for some of the tasks
                # lets imagine following sequence of actions:
                # task 1 fails, with some usefule message in the logfile, i.e. after 100 primaries the SHIELD-HIT12A binary crashed
                # then the useful logfiles are being sent to the backend
                # task 2 fails later, but here the SHIELD-HIT12A binary crashes at the beginning of the simulation, without producing of the logfiles
                # then again the logfiles are being sent to the backend, but this time they are empty
                # so the useful logfiles are overwritten by the empty ones
                # we temporarily disable sending logfiles to the backend
                # sending_logfiles_status = send_simulation_logfiles(simulation_id=simulation_id,
                #                                                 update_key=update_key,
                #                                                 logfiles=logfiles)
                # if not sending_logfiles_status:
                #     logging.error("Sending logfiles failed for task %s", task_id)
            
            # finally we return from the celery task, returning the logfiles and stdout/stderr as result
            return {
                "logfiles": logfiles,
                "stdout": command_stdout,
                "stderr": command_stderr,
                "simulation_id": simulation_id,
                "update_key": update_key
            }

        # otherwise we have simulation output
        logging.debug("Converting simulation results to JSON")
        estimators = estimators_to_list(estimators_dict=estimators_dict,
                                        dir_path=Path(tmp_work_dir))

        # We do not have any information if monitoring process sent the last update
        # so we send it here to make sure that we have the end_time and COMPLETED state
        end_time = datetime.utcnow().isoformat(sep=" ")
        update_dict = {"task_state": EntityState.COMPLETED.value, "end_time": end_time}
        send_task_update(simulation_id, task_id, update_key, update_dict)

        # finally return from the celery task, returning the estimators and stdout/stderr as result
        # the estimators will be merged by subsequent celery task
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


    if average_estimators:
        # send results to the backend and mark whole simulation as completed
        sending_results_ok = send_simulation_results(simulation_id=simulation_id,
                                                     update_key=update_key,
                                                     estimators=averaged_estimators)
        if not sending_results_ok:
            final_result["estimators"] = averaged_estimators

    return final_result
