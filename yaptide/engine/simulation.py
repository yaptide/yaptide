import fnmatch
import logging
import shutil
import tarfile
import tempfile
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
    get_tmp_dir,
    read_file_offline,
    read_fluka_file,
    read_shieldhit_file,
)
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, update_simulation_state
from yaptide.routes.common_sim_routes import store_partial_results, store_results
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import merge_simulation_outputs, simulation_logfiles, write_simulation_input_files

# prefix of the task working directories, so the ones left behind can be found
WORK_DIR_PREFIX = "yaptide_task_"
# the result files of the simulators
RESULT_PATTERNS = ("*.bdo", "*_fort.*")


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
    saved: Callable[[str, int], None],
) -> dict:
    """Runs one simulation task in work_dir and returns what the engine needs from it

    The result files go to storage under the returned "result_key", for the merge; work_dir is removed.
    Progress goes to report while the simulator runs; the final state of the task is in the returned "final_update".
    Each save the simulator makes before the end goes to storage under the same key, passed to saved with its
    primaries.
    """
    logging.info("Running simulation, simulation_id: %s, task_id: %d, directory: %s", simulation_id, task_id, work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    key = result_storage.work_key(simulation_id, task_id)
    try:
        write_simulation_input_files(files_dict=files_dict, output_dir=work_dir)
        if sim_type == "shieldhit":
            simulation_result = run_single_simulation_for_shieldhit(work_dir, task_id, simulation_id, report, saved)
        elif sim_type == "fluka":
            simulation_result = run_single_simulation_for_fluka(work_dir, task_id, simulation_id, report)
        else:
            raise ValueError(f"Unknown simulator type: {sim_type}")
        if simulation_result.output_files:
            # the simulator has ended, nothing rewrites the files any more
            result_storage.put_file(key, pack_results(work_dir))
        else:
            logfiles = simulation_logfiles(path=work_dir)
    except BaseException:
        # a save stored before a cancel would stay in storage
        try:
            result_storage.delete_objects(key)
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Removing the saved results of task %d failed", task_id)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not simulation_result.output_files:
        logging.info("Simulation failed for task %d", task_id)
        return {
            "logfiles": logfiles,
            "stdout": simulation_result.command_stdout,
            "stderr": simulation_result.command_stderr,
            "final_update": {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")},
        }

    # the monitor may have missed the last lines of the log, so the final state comes with the result
    return {
        "result_key": key,
        "final_update": {
            "task_state": EntityState.COMPLETED.value,
            "end_time": datetime.utcnow().isoformat(sep=" "),
            "simulated_primaries": simulation_result.requested_primaries,
            "requested_primaries": simulation_result.requested_primaries,
        },
    }


def run_single_simulation_for_shieldhit(
    work_dir: Path,
    task_id: int,
    simulation_id: Optional[int],
    report: Callable[[dict], None],
    saved: Callable[[str, int], None],
) -> SimulationTaskResult:
    """Function running single simulation for shieldhit"""
    command_as_list = command_to_run_shieldhit(dir_path=work_dir, task_id=task_id)
    logging.info("Command to run SHIELD-HIT12A: %s", " ".join(command_as_list))
    log_path = work_dir / f"shieldhit_{task_id:04d}.log"
    event = threading.Event()
    monitor = start_monitor(
        read_shieldhit_file,
        event,
        filepath=log_path,
        simulation_id=simulation_id,
        task_id=task_id,
        report=report,
        on_save=lambda primaries: store_save(
            work_dir, result_storage.work_key(simulation_id, task_id), primaries, saved
        ),
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


class TornSave(Exception):
    """The simulator's next save began while the last one was packed (its log is read up to a second late)"""


def pack_results(work_dir: Path) -> Path:
    """Packs the result files into one archive in work_dir; raises if the simulator rewrote one meanwhile"""
    result_files = sorted(path for pattern in RESULT_PATTERNS for path in work_dir.glob(pattern))
    before = [(path.stat().st_mtime_ns, path.stat().st_size) for path in result_files]
    archive = work_dir / "results.tar.gz"
    # the fastest compression: it saves most where the results are sparse, and the simulator shares the core
    with tarfile.open(archive, "w:gz", compresslevel=1) as tar:
        for result_file in result_files:
            tar.add(result_file, arcname=result_file.name)
    if before != [(path.stat().st_mtime_ns, path.stat().st_size) for path in result_files]:
        archive.unlink()
        raise TornSave(f"result files in {work_dir} changed while packed")
    return archive


def store_save(work_dir: Path, key: str, primaries: int, saved: Callable[[str, int], None]) -> None:
    """Stores the result files of a finished save: the simulator rewrites them in place at its next save"""
    try:
        result_storage.put_file(key, pack_results(work_dir))
        saved(key, primaries)
    except TornSave:
        logging.info("Save of %s at %d primaries skipped, the next one was under way", work_dir, primaries)
    except Exception:  # skipcq: PYL-W0703
        # a missed save only delays the partial results, the task goes on
        logging.exception("Storing the save of %s at %d primaries failed", work_dir, primaries)


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


def extract_results(archive: Path, task_dir: Path, max_bytes: float) -> int:
    """Unpacks a task's result files, up to max_bytes; anything but result files raises, as does more data

    The saves of HPC tasks come from the cluster. Returns the bytes unpacked.
    """
    members, unpacked = [], 0
    with tarfile.open(archive, "r:gz") as tar:
        # read one by one, so a long archive is refused before it is read to the end
        for member in tar:
            unpacked += member.size
            if not (member.isfile() and any(fnmatch.fnmatchcase(member.name, p) for p in RESULT_PATTERNS)):
                raise ValueError(f"{member.name!r} in {archive.name} is not a result file")
            if "/" in member.name or unpacked > max_bytes:
                raise ValueError(f"{archive.name} holds too much or nested files")
            members.append(member)
        tar.extractall(task_dir, members=members, filter="data")
    return unpacked


def merge_stored(keys: list[str], max_bytes: float = float("inf")) -> list[dict]:
    """Merges the result files the tasks stored under the keys, at most max_bytes of them; a missing one raises"""
    with tempfile.TemporaryDirectory(dir=get_tmp_dir()) as merge_dir:
        task_dirs = []
        for number, key in enumerate(keys):
            archive = Path(merge_dir) / f"{number}.tar.gz"
            result_storage.get_file(key, archive)
            task_dir = Path(merge_dir) / str(number)
            max_bytes -= extract_results(archive, task_dir, max_bytes)
            archive.unlink()
            task_dirs.append(task_dir)
        return merge_simulation_outputs(task_dirs)


def merge_and_store(simulation_id: int, keys: list[str]) -> bool:
    """Merges the result files the finished tasks stored and stores the results

    Returns whether there was anything to store; a simulation cancelled meanwhile keeps its state.
    """
    with backend_app().app_context():
        try:
            simulation = fetch_simulation_by_sim_id(simulation_id)
            if simulation is None:
                return False
            update_simulation_state(simulation, {"job_state": EntityState.MERGING_RUNNING.value})
            estimators = merge_stored(keys)
            if estimators:
                store_results(simulation, estimators)
            return bool(estimators)
        finally:
            db.session.remove()


def merge_and_store_partial(
    simulation_id: int, keys: list[str], primaries: int, max_bytes: float = float("inf")
) -> bool:
    """Merges the latest saves of the tasks, at most max_bytes of result files, into the simulation's partial
    results; whether they were stored
    """
    with backend_app().app_context():
        try:
            simulation = fetch_simulation_by_sim_id(simulation_id)
            if simulation is None:
                return False
            estimators = merge_stored(keys, max_bytes)
            return bool(estimators) and store_partial_results(simulation, estimators, primaries)
        finally:
            db.session.remove()
