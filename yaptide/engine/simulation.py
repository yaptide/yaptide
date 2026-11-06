import fnmatch
import logging
import shutil
import struct
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from yaptide.application import create_app
from yaptide.batch import bdo_pages, result_format, watcher
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
# result files in a task's archive: one per output of the simulation
MAX_RESULT_FILES = 10_000


@dataclass
class SimulationTaskResult:
    """Class representing result of single simulation task"""

    process_exit_success: bool
    command_stdout: str
    command_stderr: str
    simulated_primaries: int
    requested_primaries: int
    output_files: list[Path]


# how often a running task asks whether the user wants it finished early
FINISH_CHECK_SECONDS = 5


class Finisher:
    """Finishes a task early when the user asks (finish_requested, asked at most every FINISH_CHECK_SECONDS): a
    SHIELD-HIT12A run is stopped between two saves and its last whole save stays as its results; FLUKA gets its
    stop file and ends its cycle with the results so far. finished: None while not asked, then whether results stay
    """

    def __init__(self, sim_type: str, work_dir: Path, log_path: Optional[Path], requested: Callable[[], bool]):
        self.sim_type = sim_type
        self.work_dir = work_dir
        self.log_path = log_path
        self.requested = requested
        self.last_check = float("-inf")
        self.finished: Optional[bool] = None
        # the primaries of the simulator's last save
        self.saved_primaries = 0

    def __call__(self, process) -> None:
        """Called every second while the simulator runs"""
        if self.finished is not None or time.monotonic() - self.last_check < FINISH_CHECK_SECONDS:
            return
        self.last_check = time.monotonic()
        try:
            if not self.requested():
                return
        except Exception as error:  # skipcq: PYL-W0703 - the task goes on
            logging.warning("Asking whether to finish %s early failed: %s", self.work_dir, error)
            return
        logging.info("Finishing %s early", self.work_dir)
        if self.sim_type == "fluka":
            for run_dir in self.work_dir.glob("fluka_*"):
                if run_dir.is_dir():
                    (run_dir / watcher.FLUKA_STOP_FILE).touch()
            # FLUKA ends by itself: its results are there if it wrote them
            self.finished = True
            return
        self.finished = watcher.stop_at_whole_save(process.pid, self.work_dir, self.log_path)
        if not self.finished:
            watcher.set_aside_unfinished(self.work_dir)


def run_simulation(
    files_dict: dict,
    task_id: int,
    sim_type: str,
    work_dir: Path,
    simulation_id: Optional[int],
    report: Callable[[dict], None],
    saved: Callable[[str, int], None],
    finish_requested: Callable[[], bool] = lambda: False,
) -> dict:
    """Runs one simulation task in work_dir and returns what the engine needs from it

    The result files go to storage under the returned "result_key", for the merge; work_dir is removed.
    Progress goes to report while the simulator runs; the final state of the task is in the returned "final_update".
    Each save the simulator makes before the end goes to storage under the same key, passed to saved with its
    primaries. When finish_requested says so, the task finishes early (Finisher): its last whole save is its result.
    """
    logging.info("Running simulation, simulation_id: %s, task_id: %d, directory: %s", simulation_id, task_id, work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    key = result_storage.work_key(simulation_id, task_id)
    try:
        write_simulation_input_files(files_dict=files_dict, output_dir=work_dir)
        log_path = work_dir / f"shieldhit_{task_id:04d}.log" if sim_type == "shieldhit" else None
        finisher = Finisher(sim_type, work_dir, log_path, finish_requested)
        if sim_type == "shieldhit":
            simulation_result = run_single_simulation_for_shieldhit(
                work_dir, task_id, simulation_id, report, saved, finisher
            )
        elif sim_type == "fluka":
            simulation_result = run_single_simulation_for_fluka(work_dir, task_id, simulation_id, report, finisher)
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

    if not simulation_result.output_files and finisher.finished is not None:
        logging.info("Task %d finished early without a whole save: nothing of it goes into the results", task_id)
        return {
            "final_update": {"task_state": EntityState.CANCELED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
        }
    if not simulation_result.output_files:
        logging.info("Simulation failed for task %d", task_id)
        return {
            "logfiles": logfiles,
            "stdout": simulation_result.command_stdout,
            "stderr": simulation_result.command_stderr,
            "final_update": {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")},
        }

    if finisher.finished:
        # finished early: the primaries of its last save (FLUKA's results carry their own)
        update = {
            "task_state": EntityState.COMPLETED.value,
            "end_time": datetime.utcnow().isoformat(sep=" "),
            "finished_early": True,
        }
        if sim_type == "shieldhit":
            update["simulated_primaries"] = finisher.saved_primaries
        return {"result_key": key, "final_update": update}
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
    finisher: Optional[Finisher] = None,
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
        on_save=lambda primaries: on_save(work_dir, simulation_id, task_id, primaries, saved, finisher),
    )
    try:
        process_exit_success, command_stdout, command_stderr = execute_simulation_subprocess(
            dir_path=work_dir, command_as_list=command_as_list, check=finisher
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


def on_save(
    work_dir: Path,
    simulation_id: Optional[int],
    task_id: int,
    primaries: int,
    saved: Callable[[str, int], None],
    finisher: Optional[Finisher],
) -> None:
    """The simulator saved its results along the way: noted for a finish, stored for the partial results"""
    if finisher is not None:
        finisher.saved_primaries = primaries
    store_save(work_dir, result_storage.work_key(simulation_id, task_id), primaries, saved)


def run_single_simulation_for_fluka(
    work_dir: Path,
    task_id: int,
    simulation_id: Optional[int],
    report: Callable[[dict], None],
    finisher: Optional[Finisher] = None,
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
            dir_path=work_dir, command_as_list=command_as_list, check=finisher
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


# the pages a save of a task is stored with: the ones of partial results (volumes and particle lists wait for the end)
SAVED_MODES = {result_format.LIVE, result_format.ON_DEMAND}


def pack_results(work_dir: Path, partial: bool = False) -> Path:
    """Packs the result files into one archive in work_dir; raises if the simulator rewrote one meanwhile. For a save
    along the way (partial), a SHIELD-HIT12A file goes with the pages of partial results only (bdo_pages)
    """
    result_files = sorted(path for pattern in RESULT_PATTERNS for path in work_dir.glob(pattern))
    before = [(path.stat().st_mtime_ns, path.stat().st_size) for path in result_files]
    archive = work_dir / "results.tar.gz"
    # the fastest compression: it saves most where the results are sparse, and the simulator shares the core
    try:
        with tempfile.TemporaryDirectory(dir=work_dir, prefix=".pages_") as pages_dir, tarfile.open(
            archive, "w:gz", compresslevel=1
        ) as tar:
            for result_file in result_files:
                if partial and result_file.suffix == ".bdo":
                    copy = Path(pages_dir) / result_file.name
                    bdo_pages.copy_pages(
                        result_file,
                        copy,
                        lambda info: result_format.partial_mode(info.dimensions, info.mcpl) in SAVED_MODES,
                    )
                    tar.add(copy, arcname=result_file.name)
                else:
                    tar.add(result_file, arcname=result_file.name)
    except bdo_pages.BdoError as error:
        archive.unlink(missing_ok=True)
        raise TornSave(f"a result file in {work_dir} is cut short: {error}") from error
    except OSError as error:
        # a file the simulator truncated while it was read ("unexpected end of data")
        archive.unlink(missing_ok=True)
        raise TornSave(f"result files in {work_dir} changed while packed: {error}") from error
    if before != [(path.stat().st_mtime_ns, path.stat().st_size) for path in result_files]:
        archive.unlink()
        raise TornSave(f"result files in {work_dir} changed while packed")
    return archive


def store_save(work_dir: Path, key: str, primaries: int, saved: Callable[[str, int], None]) -> None:
    """Stores the result files of a finished save: the simulator rewrites them in place at its next save"""
    try:
        result_storage.put_file(key, pack_results(work_dir, partial=True))
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
    # a limit is set for the saves from the cluster, of SHIELD-HIT12A only
    patterns = RESULT_PATTERNS if max_bytes == float("inf") else ("*.bdo",)
    members, unpacked = [], 0
    with tarfile.open(archive, "r:gz") as tar:
        # read one by one, so a long archive is refused before it is read to the end
        for member in tar:
            unpacked += member.size
            if not (member.isfile() and any(fnmatch.fnmatchcase(member.name, p) for p in patterns)):
                raise ValueError(f"{member.name!r} in {archive.name} is not a result file")
            if "/" in member.name or unpacked > max_bytes or len(members) >= MAX_RESULT_FILES:
                raise ValueError(f"{archive.name} holds too much or nested files")
            members.append(member)
        tar.extractall(task_dir, members=members, filter="data")
    for member in members:
        if member.name.endswith(".bdo"):
            check_bdo(task_dir / member.name)
    return unpacked


def check_bdo(path: Path) -> None:
    """Raises ValueError unless the file is a SHIELD-HIT12A result file whose every entry fits in it: its reader
    allocates the memory an entry declares, a few bytes may declare terabytes
    """
    size = path.stat().st_size
    with open(path, "rb") as file:
        # magic number, byte order and version, then entries: id, numpy type and number of items, the items
        if not file.read(24).startswith(b"xSH12AII"):
            raise ValueError(f"{path.name} is not a SHIELD-HIT12A result file")
        while file.tell() < size:
            header = file.read(24)
            if len(header) < 24:
                raise ValueError(f"{path.name} ends within an entry")
            _, kind, count = struct.unpack("<Q8sQ", header)
            try:
                itemsize = np.dtype(kind.rstrip(b"\0").decode("ascii")).itemsize
            except (TypeError, ValueError):  # UnicodeDecodeError is one
                raise ValueError(f"{path.name} has an entry of an unknown type") from None
            if count * itemsize > size - file.tell():
                raise ValueError(f"{path.name} has an entry larger than the file")
            file.seek(count * itemsize, 1)


class PageWriter:
    """Puts the pages of one merge into object storage as they are merged, in ZARR_FORMAT under a revision of their
    own; the database gets them while the storage is not configured or fails
    """

    def __init__(self, simulation_id: Optional[int]):
        """Pages of the simulation's merge"""
        self.simulation_id = simulation_id
        self.revision = result_storage.new_revision()
        self.use_storage = simulation_id is not None and result_storage.configured()
        self.written: list[str] = []

    def __call__(self, name: str, number: int, page: dict, values: np.ndarray) -> dict:
        """Stores a merged page; the page entry store_results takes"""
        if self.use_storage:
            prefix = result_storage.page_prefix(self.simulation_id, name, number, self.revision)
            try:
                size = result_storage.put_page_files(prefix, result_format.page_files(page, values))
                self.written.append(prefix)
                return {
                    "metadata": page["metadata"],
                    "dimensions": page["dimensions"],
                    "stored": {"key": prefix, "size": size, "format": result_storage.ZARR_FORMAT},
                }
            except Exception:  # skipcq: PYL-W0703
                logging.exception(
                    "Storing results of simulation %d failed, the rest goes to the database", self.simulation_id
                )
                self.use_storage = False
        return result_format.json_page(page, values.tolist())


def merge_stored(
    keys: list[str],
    max_bytes: float = float("inf"),
    simulation_id: Optional[int] = None,
    modes: Optional[set] = None,
    pages: Optional[dict] = None,
) -> list[dict]:
    """Merges the result files the tasks stored under the keys, at most max_bytes of them; a missing one raises

    With the simulation's id the pages go to object storage as they are merged (PageWriter), the estimators then
    point at them. The task archives are fetched and unpacked one at a time onto disk; the merge reads one file at a
    time. With modes (result_format.partial_modes), only the pages of those modes; with pages (estimator -> page
    numbers), only those pages.
    """
    writer = PageWriter(simulation_id)
    with tempfile.TemporaryDirectory(dir=get_tmp_dir()) as merge_dir:
        task_dirs = []
        for number, key in enumerate(keys):
            archive = Path(merge_dir) / f"{number}.tar.gz"
            result_storage.get_file(key, archive)
            task_dir = Path(merge_dir) / str(number)
            max_bytes -= extract_results(archive, task_dir, max_bytes)
            archive.unlink()
            task_dirs.append(task_dir)
        try:
            return merge_simulation_outputs(task_dirs, writer, modes, pages)
        except BaseException:
            result_storage.delete_pages(writer.written)
            raise


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
            estimators = merge_stored(keys, simulation_id=simulation_id)
            if estimators:
                store_results(simulation, estimators)
            return bool(estimators)
        finally:
            db.session.remove()


def merge_and_store_partial(
    simulation_id: int,
    keys: list[str],
    primaries: int,
    max_bytes: float = float("inf"),
    kind: str = result_format.LIVE,
    pages: Optional[list] = None,
) -> bool:
    """Merges the latest saves of the tasks, at most max_bytes of result files, into the simulation's partial
    results of the kind: the live pages, or (ON_DEMAND) the pages the user asked for ((estimator, page number)
    pairs; the others keep what they had); whether they were stored
    """
    with backend_app().app_context():
        try:
            simulation = fetch_simulation_by_sim_id(simulation_id)
            if simulation is None:
                return False
            if kind == result_format.LIVE:
                estimators = merge_stored(keys, max_bytes, simulation_id, result_format.kind_modes(kind))
            else:
                selected = result_format.pages_by_estimator(pages or ())
                estimators = merge_stored(keys, max_bytes, simulation_id, None, selected) if selected else []
            return bool(estimators) and store_partial_results(simulation, estimators, primaries)
        finally:
            db.session.remove()
