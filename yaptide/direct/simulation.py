import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from yaptide.direct.backend_client import (
    FINAL_POST_ATTEMPTS,
    send_job_state,
    send_simulation_logfiles,
    send_simulation_results,
)
from yaptide.direct.pymc import (
    command_to_run_fluka,
    command_to_run_shieldhit,
    execute_simulation_subprocess,
    read_file_offline,
    read_fluka_file,
    read_shieldhit_file,
)
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import merge_simulation_outputs, simulation_logfiles, write_simulation_input_files

# prefix of the task working directories, so the ones left behind can be found
WORK_DIR_PREFIX = "yaptide_task_"


@dataclass
class SimulationTaskResult:
    """Class representing result of single simulation task"""

    process_exit_success: bool
    command_stdout: str
    command_stderr: str
    simulated_primaries: int
    requested_primaries: int
    output_files: list[Path]


def run_simulation(
    files_dict: dict,
    task_id: int,
    sim_type: str,
    work_dir: Path,
    simulation_id: Optional[int],
    report: Callable[[dict], None],
) -> dict:
    """Runs one simulation task in work_dir and returns what finish_simulation needs from it

    The result files stay in work_dir, finish_simulation merges them and removes the directory.
    Progress goes to report while the simulator runs; the final state of the task is in the returned "final_update".
    """
    logging.info("Running simulation, simulation_id: %s, task_id: %d, directory: %s", simulation_id, task_id, work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_simulation_input_files(files_dict=files_dict, output_dir=work_dir)
        if sim_type == "shieldhit":
            simulation_result = run_single_simulation_for_shieldhit(work_dir, task_id, simulation_id, report)
        elif sim_type == "fluka":
            simulation_result = run_single_simulation_for_fluka(work_dir, task_id, simulation_id, report)
        else:
            raise ValueError(f"Unknown simulator type: {sim_type}")
    except BaseException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    if not simulation_result.output_files:
        logging.info("Simulation failed for task %d", task_id)
        logfiles = simulation_logfiles(path=work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)
        return {
            "logfiles": logfiles,
            "stdout": simulation_result.command_stdout,
            "stderr": simulation_result.command_stderr,
            "final_update": {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")},
        }

    # the monitor may have missed the last lines of the log, so the final state comes with the result
    return {
        "output_dir": str(work_dir),
        "final_update": {
            "task_state": EntityState.COMPLETED.value,
            "end_time": datetime.utcnow().isoformat(sep=" "),
            "simulated_primaries": simulation_result.requested_primaries,
            "requested_primaries": simulation_result.requested_primaries,
        },
    }


def run_single_simulation_for_shieldhit(
    work_dir: Path, task_id: int, simulation_id: Optional[int], report: Callable[[dict], None]
) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_shieldhit(dir_path=work_dir, task_id=task_id)
    logging.info("Command to run SHIELD-HIT12A: %s", " ".join(command_as_list))
    log_path = work_dir / f"shieldhit_{task_id:04d}.log"
    event = threading.Event()
    monitor = start_monitor(
        read_shieldhit_file, event, filepath=log_path, simulation_id=simulation_id, task_id=task_id, report=report
    )
    try:
        process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
            dir_path=work_dir, command_as_list=command_as_list
        )
    finally:
        event.set()
        monitor.join()
    logging.info("SHIELD-HIT12A process finished with status %s", process_exit_success)
    simulated_primaries, requested_primaries = read_file_offline(log_path)

    output_files = sorted(work_dir.glob("*.bdo"))
    if not output_files:
        logging.error("No *.bdo files found in %s", work_dir)
    return SimulationTaskResult(
        process_exit_success=process_exit_success,
        command_stdout=command_stdout,
        command_stderr=command_stderr,
        simulated_primaries=simulated_primaries,
        requested_primaries=requested_primaries,
        output_files=output_files,
    )


def run_single_simulation_for_fluka(
    work_dir: Path, task_id: int, simulation_id: Optional[int], report: Callable[[dict], None]
) -> SimulationTaskResult:
    """Function running single simulation for fluka"""
    command_as_list = command_to_run_fluka(dir_path=work_dir, task_id=task_id)
    logging.info("Command to run FLUKA: %s", " ".join(command_as_list))
    event = threading.Event()
    # fluka writes its log into a directory with the PID of its process in the name, so the monitor gets the directory
    monitor = start_monitor(
        read_fluka_file, event, dirpath=work_dir, simulation_id=simulation_id, task_id=task_id, report=report
    )
    try:
        process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
            dir_path=work_dir, command_as_list=command_as_list
        )
    finally:
        event.set()
        monitor.join()
    logging.info("Fluka process finished with status %s", process_exit_success)

    output_files = sorted(work_dir.glob("*_fort.*"))
    if not output_files:
        logging.error("No *_fort.* files found in %s", work_dir)
    return SimulationTaskResult(
        process_exit_success=process_exit_success,
        command_stdout=command_stdout,
        command_stderr=command_stderr,
        simulated_primaries=0,
        requested_primaries=0,
        output_files=output_files,
    )


def start_monitor(target: Callable, event: threading.Event, **kwargs) -> threading.Thread:
    """Starts a thread following the simulator's log and reporting progress until the event is set"""
    thread = threading.Thread(
        target=target,
        kwargs={"event": event, "logging_level": logging.getLogger().getEffectiveLevel(), **kwargs},
        daemon=True,
    )
    thread.start()
    return thread


# skipcq: PY-R1000
def finish_simulation(
    results: list[dict],
    simulation_id: Optional[int],
    update_key: Optional[str],
    cancelled: Callable[[], bool] = lambda: False,
) -> dict:
    """Merges the tasks' result files, sends the results (or marks the simulation failed) and removes the task dirs

    Nothing is sent when the simulation was cancelled while merging.
    """
    logging.debug("Merging results from %d tasks", len(results))
    output_dirs = [Path(result["output_dir"]) for result in results if "output_dir" in result]
    try:
        if simulation_id and update_key:
            send_job_state(simulation_id, update_key, {"job_state": EntityState.MERGING_RUNNING.value})

        # a directory can be missing after a restart of the Ray head
        missing = [str(path) for path in output_dirs if not path.is_dir()]
        missing += [
            f"result with keys {sorted(result)}" for result in results if not {"output_dir", "logfiles"} & set(result)
        ]
        for item in missing:
            logging.error("Results of a task are missing: %s", item)
        merged_estimators = [] if missing else merge_simulation_outputs(output_dirs)
    finally:
        for path in output_dirs:
            shutil.rmtree(path, ignore_errors=True)

    logfiles = {}
    for result in results:
        logfiles.update(result.get("logfiles", {}))

    final_result = {"end_time": datetime.utcnow().isoformat(sep=" ")}
    if cancelled():
        return final_result

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
        send_job_state(
            simulation_id,
            update_key,
            {"job_state": EntityState.FAILED.value, "end_time": final_result["end_time"]},
            attempts=FINAL_POST_ATTEMPTS,
        )

    return final_result
