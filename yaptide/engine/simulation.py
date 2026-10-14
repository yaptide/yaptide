import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from yaptide.application import create_app
from yaptide.engine.pymc import (
    command_to_run_fluka,
    command_to_run_shieldhit,
    execute_simulation_subprocess,
    read_file_offline,
    read_fluka_file,
    read_shieldhit_file,
)
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, update_simulation_state
from yaptide.routes.common_sim_routes import store_results
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
    """Runs one simulation task in work_dir and returns what the engine needs from it

    The result files stay in work_dir, the merge reads them and removes the directory.
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


@lru_cache(maxsize=1)
def backend_app():
    """The backend's app in this process, for its database and storage"""
    return create_app()


def merge_and_store(simulation_id: int, output_dirs: list[str]) -> bool:
    """Merges the result files of the finished tasks, stores them and removes the task directories

    Returns whether there was anything to store; a simulation cancelled meanwhile keeps its state.
    """
    with backend_app().app_context():
        try:
            simulation = fetch_simulation_by_sim_id(simulation_id)
            if simulation is None:
                return False
            update_simulation_state(simulation, {"job_state": EntityState.MERGING_RUNNING.value})
            estimators = merge_simulation_outputs([Path(path) for path in output_dirs])
            if estimators:
                store_results(simulation, estimators)
            return bool(estimators)
        finally:
            db.session.remove()
            for path in output_dirs:
                shutil.rmtree(path, ignore_errors=True)
