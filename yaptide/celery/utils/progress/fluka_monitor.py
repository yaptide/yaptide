from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Iterator, Optional, Tuple
from yaptide.batch.watcher import TIMEOUT_MATCH

from yaptide.celery.utils.requests import send_task_update
from yaptide.utils.enums import EntityState

# templates for regex matching output from `<simulation>_<no>.out` file
S_OK_OUT_INIT = re.compile(r"^ Total time used for initialization:")
S_OK_OUT_START = re.compile(r"^1NUMBER OF BEAM")
S_OK_OUT_IN_PROGRESS = re.compile(r"^ NEXT SEEDS:")
S_OK_OUT_COLLECTED = re.compile(r"^ All cases handled by Feeder")
S_OK_OUT_FIN = re.compile(r"^ \* ======(?:( )*?)End of FLUKA [\w\-.]* run (?:( )*?) ====== \*")

# for larger number of particles values are shifted accordingly to fit all digits, e.g. for 1e+12 particles:
# "              1          999999999999          999999999999         2.8598309E-04         1.0000000E+30                 0       "
S_OK_OUT_PROGRESS_REMAINING_LINE_EXAMPLE = \
    "     980000                 20000                 20000             1.8515483E-04         1.0000000E+30             44182       "

logger = logging.getLogger(__name__)


def parse_progress_remaining_line(line: str) -> Optional[Tuple[int, int]]:
    """Function parsing the line with progress remaining information.

    Args:
        line (str): line to be parsed
    Returns:
        Tuple[int, int]: tuple with two integers representing the progress and remaining.
        If the line cannot be parsed None is returned.
    """
    list = line.split()
    # expecting 6 sections which are int or floats
    if len(list) != 6:
        return None
    try:
        [float(x) for x in list]
    except ValueError:
        return None
    return (int(list[0]), int(list[1]))


@dataclass
class TaskDetails:
    simulation_id: int
    task_id: str
    update_key: str


def time_now_utc() -> datetime:
    """Function returning current time in UTC timezone."""
    # because datetime.utcnow() is deprecated
    return datetime.now(timezone.utc)


def read_fluka_out_file(linte_iterator: Iterator[str],
                        next_backend_update_time: int,
                        details: TaskDetails,
                        varbose: bool = False) -> None:
    """Function reading the fluka output file and raporting progress to the backend."""
    in_progress = False
    requested_primaries = 0
    update_time = 0
    for line in linte_iterator:
        utc_now = time_now_utc()
        if re.match(S_OK_OUT_START, line):
            logger.debug("Found start of the simulation")
            continue
        if re.match(S_OK_OUT_IN_PROGRESS, line):
            in_progress = True
            if varbose:
                logger.debug("Found progress line")
            continue
        if re.match(S_OK_OUT_COLLECTED, line):
            in_progress = False
            if varbose:
                logger.debug("Found end of simulation calculation line")
            continue
        if re.match(S_OK_OUT_FIN, line):
            logger.debug("Found end of the simulation")
            break
        if in_progress:
            res = parse_progress_remaining_line(line)
            if res:
                progress, remainder = res
                logger.debug("Found progress remaining line with progress: %s, remaining: %s", progress, remainder)
                if not requested_primaries:
                    requested_primaries = progress + remainder
                    up_dict = {
                        "simulated_primaries": progress,
                        "requested_primaries": requested_primaries,
                        "start_time": utc_now.isoformat(sep=" "),
                        "task_state": EntityState.RUNNING.value
                    }
                    send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
                else:
                    if (utc_now.timestamp() - update_time < next_backend_update_time  # do not send update too often
                            and requested_primaries > progress):
                        continue
                    update_time = utc_now.timestamp()
                    up_dict = {
                        "simulated_primaries": progress,
                    }
                    send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
                continue
        # handle generator timeout
        if re.search(TIMEOUT_MATCH, line):
            logging.error("Simulation watcher %s timed out", details.task_id)
            up_dict = {"task_state": EntityState.FAILED.value, "end_time": time_now_utc().isoformat(sep=" ")}
            send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
            return

    logging.info("Parsing log file for task %s finished", details.task_id)
    up_dict = {
        "simulated_primaries": requested_primaries,
        "end_time": utc_now.isoformat(sep=" "),
        "task_state": EntityState.COMPLETED.value
    }
    logging.info("Sending final update for task %s", details.task_id)
    send_task_update(details.simulation_id, details.task_id, details.update_key, up_dict)
