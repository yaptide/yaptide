import contextlib
from dataclasses import dataclass
import logging
import tempfile
from datetime import datetime
from pathlib import Path
import threading
from typing import Optional

from yaptide.celery.utils.pymc import (average_estimators, command_to_run_fluka, command_to_run_shieldhit,
                                       execute_simulation_subprocess, get_fluka_estimators, get_shieldhit_estimators,
                                       get_tmp_dir, read_file, read_file_offline, read_fluka_file)
from yaptide.celery.utils.requests import (send_simulation_logfiles, send_simulation_results, send_task_update)
from yaptide.celery.worker import celery_app
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import (check_and_convert_payload_to_files_dict, estimators_to_list, simulation_logfiles,
                                     write_simulation_input_files)


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task(bind=True)
def run_single_simulation(self,
                          files_dict: dict,
                          task_id: int,
                          update_key: str = '',
                          simulation_id: int = None,
                          keep_tmp_files: bool = False,
                          sim_type: str = 'shieldhit') -> dict:
    """Function running single simulation"""
    # for the purpose of running this function in pytest we would like to have some control
    # on the temporary directory used by the function

    logging.info("Running simulation, simulation_id: %s, task_id: %d", simulation_id, task_id)

    logging.info("Sending initial update for task %d, setting celery id %s", task_id, self.request.id)
    send_task_update(simulation_id, task_id, update_key, {"celery_id": self.request.id})

    # we would like to have some control on the temporary directory used by the function
    tmp_dir = get_tmp_dir()
    logging.info("Temporary directory is: %s", tmp_dir)

    # with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp_dir_path:
    # use the selected temporary directory to create a temporary directory
    with (contextlib.nullcontext(tempfile.mkdtemp(dir=tmp_dir)) if keep_tmp_files else tempfile.TemporaryDirectory(
            dir=tmp_dir)) as tmp_work_dir:

        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_work_dir))
        logging.debug("Generated input files: %s", files_dict.keys())

        if sim_type == 'shieldhit':
            simulation_result = run_single_simulation_for_shieldhit(tmp_work_dir, task_id, update_key, simulation_id)
        elif sim_type == 'fluka':
            simulation_result = run_single_simulation_for_fluka(tmp_work_dir, task_id, update_key, simulation_id)

        # there is no simulation output
        if not simulation_result.estimators_dict:
            # first we notify the backend that the task with simulation has failed
            logging.info("Simulation failed for task %d, sending update that it has failed", task_id)
            update_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
            send_task_update(simulation_id, task_id, update_key, update_dict)

            # then we send the logfiles to the backend, if available
            logfiles = simulation_logfiles(path=Path(tmp_work_dir))
            logging.info("Simulation failed, logfiles: %s", logfiles.keys())
            # the method below is in particular broken,
            # as there may be several logfiles, for some of the tasks
            # lets imagine following sequence of actions:
            # task 1 fails, with some usefule message in the logfile,
            # i.e. after 100 primaries the SHIELD-HIT12A binary crashed
            # then the useful logfiles are being sent to the backend
            # task 2 fails later, but here the SHIELD-HIT12A binary crashes
            # at the beginning of the simulation, without producing of the logfiles
            # then again the logfiles are being sent to the backend, but this time they are empty
            # so the useful logfiles are overwritten by the empty ones
            # we temporarily disable sending logfiles to the backend
            # if logfiles:
            #     pass
            # sending_logfiles_status = send_simulation_logfiles(simulation_id=simulation_id,
            #                                                 update_key=update_key,
            #                                                 logfiles=logfiles)
            # if not sending_logfiles_status:
            #     logging.error("Sending logfiles failed for task %s", task_id)

            # finally we return from the celery task, returning the logfiles and stdout/stderr as result
            return {
                "logfiles": logfiles,
                "stdout": simulation_result.command_stdout,
                "stderr": simulation_result.command_stderr,
                "simulation_id": simulation_id,
                "update_key": update_key
            }

        # otherwise we have simulation output
        logging.debug("Converting simulation results to JSON")
        estimators = estimators_to_list(estimators_dict=simulation_result.estimators_dict, dir_path=Path(tmp_work_dir))

    # We do not have any information if monitoring process sent the last update
    # so we send it here to make sure that we have the end_time and COMPLETED state
    end_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {
        "task_state": EntityState.COMPLETED.value,
        "end_time": end_time,
        "simulated_primaries": simulation_result.requested_primaries,
        "requested_primaries": simulation_result.requested_primaries
    }
    send_task_update(simulation_id, task_id, update_key, update_dict)

    # finally return from the celery task, returning the estimators and stdout/stderr as result
    # the estimators will be merged by subsequent celery task
    return {"estimators": estimators, "simulation_id": simulation_id, "update_key": update_key}


@dataclass
class SimulationTaskResult:
    """Class representing result of single simulation task"""

    process_exit_success: bool
    command_stdout: str
    command_stderr: str
    simulated_primaries: int
    requested_primaries: int
    estimators_dict: dict


def run_single_simulation_for_shieldhit(tmp_work_dir: str,
                                        task_id: int,
                                        update_key: str = '',
                                        simulation_id: int = Optional[None]) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_shieldhit(dir_path=Path(tmp_work_dir), task_id=task_id)
    logging.info("Command to run SHIELD-HIT12A: %s", " ".join(command_as_list))

    command_stdout, command_stderr = '', ''
    simulated_primaries, requested_primaries = 0, 0
    event = threading.Event()

    # start monitoring process if possible
    # is None if monitoring if monitor was not started
    task_monitor = monitor_shieldhit(event, tmp_work_dir, task_id, update_key, simulation_id)
    # run the simulation
    logging.info("Running SHIELD-HIT12A process in %s", tmp_work_dir)
    process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
        dir_path=Path(tmp_work_dir), command_as_list=command_as_list)
    logging.info("SHIELD-HIT12A process finished with status %s", process_exit_success)

    # terminate monitoring process
    if task_monitor:
        logging.debug("Terminating monitoring process for task %d", task_id)
        event.set()
        task_monitor.task.join()
        logging.debug("Monitoring process for task %d terminated", task_id)
    # if watcher didn't finish yet, we need to read the log file and send the last update to the backend
    if task_monitor:
        simulated_primaries, requested_primaries = read_file_offline(task_monitor.path_to_monitor)

    # both simulation execution and monitoring process are finished now, we can read the estimators
    estimators_dict = get_shieldhit_estimators(dir_path=Path(tmp_work_dir))

    return SimulationTaskResult(process_exit_success=process_exit_success,
                                command_stdout=command_stdout,
                                command_stderr=command_stderr,
                                simulated_primaries=simulated_primaries,
                                requested_primaries=requested_primaries,
                                estimators_dict=estimators_dict)


def run_single_simulation_for_fluka(tmp_work_dir: str,
                                    task_id: int,
                                    update_key: str = '',
                                    simulation_id: Optional[int] = None) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_fluka(dir_path=Path(tmp_work_dir), task_id=task_id)
    logging.info("Command to run FLUKA: %s", " ".join(command_as_list))

    command_stdout, command_stderr = '', ''
    simulated_primaries, requested_primaries = 0, 0
    event = threading.Event()
    # start monitoring process if possible
    # is None if monitoring if monitor was not started
    task_monitor = monitor_fluka(event, tmp_work_dir, task_id, update_key, simulation_id)

    # run the simulation
    logging.info("Running Fluka process in %s", tmp_work_dir)
    process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
        dir_path=Path(tmp_work_dir), command_as_list=command_as_list)
    logging.info("Fluka process finished with status %s", process_exit_success)

    # terminate monitoring process
    if task_monitor:
        logging.debug("Terminating monitoring process for task %s", task_id)
        event.set()
        task_monitor.task.join()
        logging.debug("Monitoring process for task %s terminated", task_id)
    # if watcher didn't finish yet, we need to read the log file and send the last update to the backend
    # TODO: implement reading of the log file for fluka after simulation was finished
    # fluka copies the file back to main direcotry from temporary directory
    # if task_monitor:
    #     simulated_primaries, requested_primaries = read_file_offline(task_monitor.path_to_monitor)

    # both simulation execution and monitoring process are finished now, we can read the estimators
    estimators_dict = get_fluka_estimators(dir_path=Path(tmp_work_dir))

    return SimulationTaskResult(process_exit_success=process_exit_success,
                                command_stdout=command_stdout,
                                command_stderr=command_stderr,
                                simulated_primaries=simulated_primaries,
                                requested_primaries=requested_primaries,
                                estimators_dict=estimators_dict)


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

    final_result = {"end_time": datetime.utcnow().isoformat(sep=" ")}

    if len(logfiles.keys()) > 0 and not send_simulation_logfiles(
            simulation_id=simulation_id, update_key=update_key, logfiles=logfiles):
        final_result["logfiles"] = logfiles

    if averaged_estimators:
        # send results to the backend and mark whole simulation as completed
        sending_results_ok = send_simulation_results(simulation_id=simulation_id,
                                                     update_key=update_key,
                                                     estimators=averaged_estimators)
        if not sending_results_ok:
            final_result["estimators"] = averaged_estimators

    return final_result


@dataclass
class MonitorTask:
    """Class representing monitoring task"""

    path_to_monitor: Path
    task: threading.Thread


def monitor_shieldhit(event: threading.Event, tmp_work_dir: str, task_id: int, update_key: str,
                      simulation_id: str) -> Optional[MonitorTask]:
    """Function monitoring progress of SHIELD-HIT12A simulation"""
    # we would like to monitor the progress of simulation
    # this is done by reading the log file and sending the updates to the backend
    # if we have update_key and simulation_id the monitoring task can submit the updates to backend
    path_to_monitor = Path(tmp_work_dir) / f"shieldhit_{task_id:04d}.log"
    if update_key and simulation_id is not None:
        current_logging_level = logging.getLogger().getEffectiveLevel()
        task = threading.Thread(target=read_file,
                                kwargs=dict(event=event,
                                            filepath=path_to_monitor,
                                            simulation_id=simulation_id,
                                            task_id=task_id,
                                            update_key=update_key,
                                            logging_level=current_logging_level))
        task.start()
        logging.info("Started monitoring process for task %d", task_id)
        return MonitorTask(path_to_monitor=path_to_monitor, task=task)

    logging.info("No monitoring processes started for task %d", task_id)
    return None


# def run_fluka_watcher(task_id, update_key, simulation_id, tmp_dir_path, ):
def monitor_fluka(event: threading.Event, tmp_work_dir: str, task_id: str, update_key: str,
                  simulation_id: str) -> Optional[MonitorTask]:
    """Function running the monitoring process for SHIELDHIT simulation"""
    # we would like to monitor the progress of simulation
    # this is done by reading the log file and sending the updates to the backend
    # if we have update_key and simulation_id the monitoring task can submit the updates to backend
    # We use dir instead path, because fluka simulator generates direcoty with PID in name of its process
    dir_to_monitor = Path(tmp_work_dir)
    if update_key and simulation_id is not None:
        current_logging_level = logging.getLogger().getEffectiveLevel()
        task = threading.Thread(target=read_fluka_file,
                                kwargs=dict(event=event,
                                            dirpath=dir_to_monitor,
                                            simulation_id=simulation_id,
                                            task_id=task_id,
                                            update_key=update_key,
                                            logging_level=current_logging_level))

        task.start()
        logging.info("Started monitoring process for task %s", task_id)
        return MonitorTask(path_to_monitor=dir_to_monitor, task=task)

    logging.info("No monitoring processes started for task %s", task_id)
    return None
