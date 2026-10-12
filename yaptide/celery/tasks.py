from dataclasses import dataclass
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
import threading
from typing import Optional

from celery.signals import worker_ready

from yaptide.batch.batch_methods import post_update
from yaptide.celery.utils.pymc import (
    command_to_run_fluka,
    command_to_run_shieldhit,
    execute_simulation_subprocess,
    get_tmp_dir,
    read_shieldhit_file,
    read_file_offline,
    read_fluka_file,
)
from yaptide.celery.utils.requests import send_simulation_logfiles, send_simulation_results, send_task_update
from yaptide.celery.simulation_worker import celery_app
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import (
    check_and_convert_payload_to_files_dict,
    merge_simulation_outputs,
    simulation_logfiles,
    write_simulation_input_files,
)


# prefix of the task working directories, so the ones left behind can be found
WORK_DIR_PREFIX = "yaptide_task_"


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task(bind=True)
def run_single_simulation(
    self,
    files_dict: dict,
    task_id: int,
    update_key: str = "",
    simulation_id: int = None,
    keep_tmp_files: bool = False,
    sim_type: str = "shieldhit",
) -> dict:
    """Function running single simulation"""
    # for the purpose of running this function in pytest we would like to have some control
    # on the temporary directory used by the function

    logging.info("Running simulation, simulation_id: %s, task_id: %d", simulation_id, task_id)

    logging.info("Sending initial update for task %d, setting celery id %s", task_id, self.request.id)
    send_task_update(simulation_id, task_id, update_key, {"celery_id": self.request.id})

    # the directory outlives the task: merge_results reads the result files from it and removes it afterwards,
    # so both must run on the same filesystem (one simulation worker); the directories of a job cancelled
    # before its merge are removed when the worker starts again
    tmp_work_dir = tempfile.mkdtemp(prefix=WORK_DIR_PREFIX, dir=get_tmp_dir())
    logging.info("Working directory is: %s", tmp_work_dir)
    try:
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_work_dir))
        logging.debug("Generated input files: %s", files_dict.keys())

        if sim_type == "shieldhit":
            simulation_result = run_single_simulation_for_shieldhit(tmp_work_dir, task_id, update_key, simulation_id)
        elif sim_type == "fluka":
            simulation_result = run_single_simulation_for_fluka(tmp_work_dir, task_id, update_key, simulation_id)

        # there is no simulation output
        if not simulation_result.output_files:
            # first we notify the backend that the task with simulation has failed
            logging.info("Simulation failed for task %d, sending update that it has failed", task_id)
            update_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
            send_task_update(simulation_id, task_id, update_key, update_dict)

            # the logfiles are returned to merge_results, which sends them to the backend
            logfiles = simulation_logfiles(path=Path(tmp_work_dir))
            logging.info("Simulation failed, logfiles: %s", logfiles.keys())
            if not keep_tmp_files:
                shutil.rmtree(tmp_work_dir, ignore_errors=True)
            return {
                "logfiles": logfiles,
                "stdout": simulation_result.command_stdout,
                "stderr": simulation_result.command_stderr,
                "simulation_id": simulation_id,
                "update_key": update_key,
            }

        # We do not have any information if monitoring process sent the last update
        # so we send it here to make sure that we have the end_time and COMPLETED state
        end_time = datetime.utcnow().isoformat(sep=" ")
        update_dict = {
            "task_state": EntityState.COMPLETED.value,
            "end_time": end_time,
            "simulated_primaries": simulation_result.requested_primaries,
            "requested_primaries": simulation_result.requested_primaries,
        }
        send_task_update(simulation_id, task_id, update_key, update_dict)

        # the result files stay on disk, merge_results reads them directly - no JSON on the way
        return {
            "output_dir": tmp_work_dir,
            "keep_output_dir": keep_tmp_files,
            "simulation_id": simulation_id,
            "update_key": update_key,
        }
    except BaseException:
        if not keep_tmp_files:
            shutil.rmtree(tmp_work_dir, ignore_errors=True)
        raise


@worker_ready.connect
def remove_stale_work_dirs(**_) -> None:
    """Removes working directories left by tasks whose merge never ran - no task is running when a worker starts"""
    for work_dir in get_tmp_dir().glob(f"{WORK_DIR_PREFIX}*"):
        logging.warning("Removing stale working directory %s", work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)


@dataclass
class SimulationTaskResult:
    """Class representing result of single simulation task"""

    process_exit_success: bool
    command_stdout: str
    command_stderr: str
    simulated_primaries: int
    requested_primaries: int
    output_files: list[Path]


def run_single_simulation_for_shieldhit(
    tmp_work_dir: str, task_id: int, update_key: str = "", simulation_id: int = Optional[None]
) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_shieldhit(dir_path=Path(tmp_work_dir), task_id=task_id)
    logging.info("Command to run SHIELD-HIT12A: %s", " ".join(command_as_list))

    command_stdout, command_stderr = "", ""
    simulated_primaries, requested_primaries = 0, 0
    event = threading.Event()

    # start monitoring process if possible
    # is None if monitoring if monitor was not started
    task_monitor = monitor_shieldhit(event, tmp_work_dir, task_id, update_key, simulation_id)
    # run the simulation
    logging.info("Running SHIELD-HIT12A process in %s", tmp_work_dir)
    process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
        dir_path=Path(tmp_work_dir), command_as_list=command_as_list
    )
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

    # both simulation execution and monitoring process are finished now, the result files are complete
    output_files = sorted(Path(tmp_work_dir).glob("*.bdo"))
    if not output_files:
        logging.error("No *.bdo files found in %s", tmp_work_dir)

    return SimulationTaskResult(
        process_exit_success=process_exit_success,
        command_stdout=command_stdout,
        command_stderr=command_stderr,
        simulated_primaries=simulated_primaries,
        requested_primaries=requested_primaries,
        output_files=output_files,
    )


def run_single_simulation_for_fluka(
    tmp_work_dir: str, task_id: int, update_key: str = "", simulation_id: Optional[int] = None
) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_fluka(dir_path=Path(tmp_work_dir), task_id=task_id)
    logging.info("Command to run FLUKA: %s", " ".join(command_as_list))

    command_stdout, command_stderr = "", ""
    simulated_primaries, requested_primaries = 0, 0
    event = threading.Event()
    # start monitoring process if possible
    # is None if monitoring if monitor was not started
    task_monitor = monitor_fluka(event, tmp_work_dir, task_id, update_key, simulation_id)

    # run the simulation
    logging.info("Running Fluka process in %s", tmp_work_dir)
    process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
        dir_path=Path(tmp_work_dir), command_as_list=command_as_list
    )
    logging.info("Fluka process finished with status %s", process_exit_success)

    # terminate monitoring process
    if task_monitor:
        logging.debug("Terminating monitoring process for task %s", task_id)
        event.set()
        task_monitor.task.join()
        logging.debug("Monitoring process for task %s terminated", task_id)
    # TO BE IMPLEMENTED
    # if watcher didn't finish yet, we need to read the log file and send the last update to the backend
    # reading of the log file for fluka after simulation was finished
    # fluka copies the file back to main directory from temporary directory

    # both simulation execution and monitoring process are finished now, the result files are complete
    output_files = sorted(Path(tmp_work_dir).glob("*_fort.*"))
    if not output_files:
        logging.error("No *_fort.* files found in %s", tmp_work_dir)

    return SimulationTaskResult(
        process_exit_success=process_exit_success,
        command_stdout=command_stdout,
        command_stderr=command_stderr,
        simulated_primaries=simulated_primaries,
        requested_primaries=requested_primaries,
        output_files=output_files,
    )


@celery_app.task
def set_merging_queued_state(results: list[dict]) -> list[dict]:
    """Celery task to set simulation state as MERGING_QUEUED"""
    logging.debug("send_state")
    simulation_id = results[0].get("simulation_id", None)
    update_key = results[0].get("update_key", None)
    if simulation_id and update_key:
        dict_to_send = {
            "sim_id": simulation_id,
            "job_state": EntityState.MERGING_QUEUED.value,
            "update_key": update_key,
        }
        post_update(dict_to_send)
    return results


@celery_app.task
def merge_results(results: list[dict]) -> dict:  # skipcq: PY-R1000
    """Merge results from multiple simulation's tasks"""
    logging.debug("Merging results from %d tasks", len(results))
    simulation_id, update_key = None, None
    for result in results:
        simulation_id = simulation_id or result.get("simulation_id")
        update_key = update_key or result.get("update_key")
    output_dirs = [Path(result["output_dir"]) for result in results if "output_dir" in result]
    try:
        if simulation_id and update_key:
            dict_to_send = {
                "sim_id": simulation_id,
                "job_state": EntityState.MERGING_RUNNING.value,
                "update_key": update_key,
            }
            post_update(dict_to_send)

        # a directory is missing after a worker restart, a result without files or logfiles comes from older code
        missing = [str(path) for path in output_dirs if not path.is_dir()]
        missing += [
            f"result with keys {sorted(result)}" for result in results if not {"output_dir", "logfiles"} & set(result)
        ]
        for item in missing:
            logging.error("Results of a task are missing: %s", item)
        merged_estimators = [] if missing else merge_simulation_outputs(output_dirs)
    finally:
        for result in results:
            if "output_dir" in result and not result.get("keep_output_dir"):
                shutil.rmtree(result["output_dir"], ignore_errors=True)

    logfiles = {}
    for result in results:
        logfiles.update(result.get("logfiles", {}))

    final_result = {"end_time": datetime.utcnow().isoformat(sep=" ")}

    if len(logfiles.keys()) > 0 and not send_simulation_logfiles(
        simulation_id=simulation_id, update_key=update_key, logfiles=logfiles
    ):
        final_result["logfiles"] = logfiles

    if merged_estimators:
        # send results to the backend and mark whole simulation as completed
        sending_results_ok = send_simulation_results(
            simulation_id=simulation_id, update_key=update_key, estimators=merged_estimators
        )
        if not sending_results_ok:
            final_result["estimators"] = merged_estimators
    elif simulation_id and update_key:
        # nothing to show - mark the simulation failed instead of leaving it merging forever
        post_update(
            {
                "sim_id": simulation_id,
                "job_state": EntityState.FAILED.value,
                "end_time": final_result["end_time"],
                "update_key": update_key,
            }
        )

    return final_result


@dataclass
class MonitorTask:
    """Class representing monitoring task"""

    path_to_monitor: Path
    task: threading.Thread


def monitor_shieldhit(
    event: threading.Event, tmp_work_dir: str, task_id: int, update_key: str, simulation_id: str
) -> Optional[MonitorTask]:
    """Function monitoring progress of SHIELD-HIT12A simulation"""
    # we would like to monitor the progress of simulation
    # this is done by reading the log file and sending the updates to the backend
    # if we have update_key and simulation_id the monitoring task can submit the updates to backend
    path_to_monitor = Path(tmp_work_dir) / f"shieldhit_{task_id:04d}.log"
    if update_key and simulation_id is not None:
        current_logging_level = logging.getLogger().getEffectiveLevel()
        task = threading.Thread(
            target=read_shieldhit_file,
            kwargs=dict(
                event=event,
                filepath=path_to_monitor,
                simulation_id=simulation_id,
                task_id=task_id,
                update_key=update_key,
                logging_level=current_logging_level,
            ),
        )
        task.start()
        logging.info("Started monitoring process for task %d", task_id)
        return MonitorTask(path_to_monitor=path_to_monitor, task=task)

    logging.info("No monitoring processes started for task %d", task_id)
    return None


def monitor_fluka(
    event: threading.Event, tmp_work_dir: str, task_id: int, update_key: str, simulation_id: int
) -> Optional[MonitorTask]:
    """Function running the monitoring process for Fluka simulation"""
    # we would like to monitor the progress of simulation
    # this is done by reading the log file and sending the updates to the backend
    # if we have update_key and simulation_id the monitoring task can submit the updates to backend
    # We use dir instead path, because fluka simulator generates direcoty with PID in name of its process
    dir_to_monitor = Path(tmp_work_dir)
    if update_key and simulation_id is not None:
        current_logging_level = logging.getLogger().getEffectiveLevel()
        task = threading.Thread(
            target=read_fluka_file,
            kwargs=dict(
                event=event,
                dirpath=dir_to_monitor,
                simulation_id=simulation_id,
                task_id=task_id,
                update_key=update_key,
                logging_level=current_logging_level,
            ),
        )

        task.start()
        logging.info("Started monitoring process for task %d", task_id)
        return MonitorTask(path_to_monitor=dir_to_monitor, task=task)

    logging.info("No monitoring processes started for task %d", task_id)
    return None
