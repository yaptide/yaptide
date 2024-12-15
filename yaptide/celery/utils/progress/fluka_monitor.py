from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import threading
from typing import Iterator, Optional, Tuple
from yaptide.batch.watcher import TIMEOUT_MATCH

from yaptide.celery.utils.requests import send_task_update
from yaptide.utils.enums import EntityState

# templates for regex matching output from `<simulation>_<no>.out` file
S_OK_OUT_INIT = "Total time used for initialization:"
S_OK_OUT_START = "1NUMBER OF BEAM"
S_OK_OUT_IN_PROGRESS = " NEXT SEEDS:"
S_TERMINATED_FROM_OUTSIDE = "  *** RUN TERMINATION FORCED FROM OUTSIDE ***"
S_OK_OUT_COLLECTED = " All cases handled by Feeder"
S_OK_OUT_FIN_PRE_CHECK = "End of FLUKA"
S_OK_OUT_FIN_PATTERN = re.compile(r"^ \* ======(?:( )*?)End of FLUKA [\w\-.]* run (?:( )*?) ====== \*")

logger = logging.getLogger(__name__)


def parse_progress_remaining_line(line: str) -> Optional[tuple[int, int]]:
    """Function parsing the line with progress remaining information.

    Args:
        line (str): line to be parsed
    Returns:
        Tuple[int, int]: tuple with two integers representing the progress and remaining.
        If the line cannot be parsed None is returned.
    """
    parts = line.split()
    # expecting 6 sections which are int or floats
    if len(parts) != 6:
        return None
    try:
        [float(x) for x in parts]
    except ValueError:
        return None
    return (int(parts[0]), int(parts[1]))


@dataclass
class TaskDetails:
    """Class holding details about the task."""

    simulation_id: int
    task_id: str
    update_key: str


def time_now_utc() -> datetime:
    """Function returning current time in UTC timezone."""
    # because datetime.utcnow() is deprecated
    return datetime.now(timezone.utc)


def utc_without_offset(utc: datetime) -> str:
    """Function returning current time in UTC timezone."""
    return utc.strftime('%Y-%m-%d %H:%M:%S.%f')


@dataclass
class ProgressDetails:
    """Class holding details about the progress."""

    utc_now: datetime
    requested_primaries: int = 0
    last_update_timestamp: int = 0


def check_progress(line: str, next_backend_update_time: int, details: TaskDetails,
                   progress_details: ProgressDetails) -> bool:
    """Function checking if the line contains progress information and sending update if needed.

    Function returns True if the line contained progress information, False otherwise.
    """
    res = parse_progress_remaining_line(line)
    if res:
        progress, remainder = res
        logger.debug("Found progress remaining line with progress: %s, remaining: %s", progress, remainder)
        if not progress_details.requested_primaries:
            progress_details.requested_primaries = progress + remainder
            up_dict = {
                "simulated_primaries": progress,
                "requested_primaries": progress_details.requested_primaries,
                "start_time": utc_without_offset(progress_details.utc_now),
                "task_state": EntityState.RUNNING.value
            }
            send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
        else:
            if (progress_details.utc_now.timestamp() - progress_details.last_update_timestamp <
                    next_backend_update_time  # do not send update too often
                    and progress_details.requested_primaries > progress):
                return True
            progress_details.last_update_timestamp = progress_details.utc_now.timestamp()
            up_dict = {
                "simulated_primaries": progress,
            }
            send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
        return True
    return False


def read_fluka_out_file(event: threading.Event,
                        line_iterator: Iterator[str],
                        next_backend_update_time: int,
                        details: TaskDetails,
                        verbose: bool = False) -> None:
    """Function reading the fluka output file and reporting progress to the backend."""
    in_progress = False
    progress_details = ProgressDetails(utc_now=time_now_utc())
    for line in line_iterator:
        if event.is_set():
            return
        progress_details.utc_now = time_now_utc()
        if in_progress:
            if check_progress(line=line,
                              next_backend_update_time=next_backend_update_time,
                              details=details,
                              progress_details=progress_details):
                continue
            if line.startswith(S_OK_OUT_COLLECTED):
                in_progress = False
                if verbose:
                    logger.debug("Found end of simulation calculation line")
                continue
        else:
            if line.startswith(S_OK_OUT_IN_PROGRESS):
                in_progress = True
                if verbose:
                    logger.debug("Found progress line")
                continue
            if line.startswith(S_OK_OUT_START):
                logger.debug("Found start of the simulation")
                continue
            if S_OK_OUT_FIN_PRE_CHECK in line and re.match(S_OK_OUT_FIN_PATTERN, line):
                logger.debug("Found end of the simulation")
                break
        # handle generator timeout
        if re.search(TIMEOUT_MATCH, line):
            logging.error("Simulation watcher %s timed out", details.task_id)
            up_dict = {"task_state": EntityState.FAILED.value, "end_time": time_now_utc().isoformat(sep=" ")}
            send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
            return

    logging.info("Parsing log file for task %s finished", details.task_id)
    up_dict = {
        "simulated_primaries": progress_details.requested_primaries,
        "end_time": utc_without_offset(progress_details.utc_now),
        "task_state": EntityState.COMPLETED.value
    }
    logging.info("Sending final update for task %d, simulated primaries %d", details.task_id,
                 progress_details.requested_primaries)
    send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)


def read_fluka_out_file_offline(sim_dir: Path) -> tuple[int, int]:
    """Reads fluka out file and returns number of simulated and requested primaries"""
    simulated_primaries = 0
    requested_primaries = 0
    in_progress = False
    out_file_path = sim_dir / "fl_sim001.out"
    if not out_file_path.exists():
        logging.error("Out file %s not found", out_file_path)
        return simulated_primaries, requested_primaries
    try:
        with open(out_file_path, 'r') as f:
            for line in f:
                logging.debug("Parsing line: %s", line.rstrip())
                if line.startswith(S_TERMINATED_FROM_OUTSIDE) or line.startswith(S_OK_OUT_COLLECTED):
                    break
                if in_progress:
                    simulated_primaries, remaining_particles = parse_progress_remaining_line(line)
                    if requested_primaries == 0:
                        requested_primaries = simulated_primaries + remaining_particles
                    in_progress = False
                else:
                    if line.startswith(S_OK_OUT_IN_PROGRESS):
                        in_progress = True
    except FileNotFoundError:
        logging.error("Log file %s not found", out_file_path)
    return simulated_primaries, requested_primaries
