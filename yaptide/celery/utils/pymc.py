import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Protocol

from pymchelper.executor.options import SimulationSettings, SimulatorType
from pymchelper.input_output import frompattern
from pymchelper.executor.runner import Runner

from celery.result import AsyncResult

from yaptide.batch.watcher import (COMPLETE_MATCH, REQUESTED_MATCH, RUN_MATCH, TIMEOUT_MATCH, log_generator)
from yaptide.celery.utils.progress.fluka_monitor import TaskDetails, read_fluka_out_file
from yaptide.celery.utils.requests import send_task_update
from yaptide.utils.enums import EntityState


def get_tmp_dir() -> Path:
    """Function to get temporary directory from environment variables."""
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


def command_to_run_shieldhit(dir_path: Path, task_id: int) -> list[str]:
    """Function to create command to run SHIELD-HIT12A."""
    settings = SimulationSettings(
        input_path=dir_path,  # skipcq: PYL-W0612 # usefull
        simulator_type=SimulatorType.shieldhit,
        simulator_exec_path=None,  # useless, we guess from PATH
        cmdline_opts="")  # useless, we could use -q in the future
    # last part of task_id gives an integer seed for random number generator
    settings.set_rng_seed(task_id)
    command_as_list = str(settings).split()
    command_as_list.append(str(dir_path))
    return command_as_list


def get_shieldhit_estimators(dir_path: Path) -> dict:
    """Function to get estimators from SHIELD-HIT12A output files."""
    estimators_dict = {}

    matching_files = list(dir_path.glob("*.bdo"))
    if len(matching_files) == 0:
        logging.error("No *.bdo files found in %s", dir_path)
        return estimators_dict

    logging.debug("Found %d *.bdo files in %s", len(matching_files), dir_path)
    files_pattern_pattern = str(dir_path / "*.bdo")
    estimators_list = frompattern(pattern=files_pattern_pattern)
    for estimator in estimators_list:
        logging.debug("Appending estimator for %s", estimator.file_corename)
        estimators_dict[estimator.file_corename] = estimator

    return estimators_dict


def command_to_run_fluka(dir_path: Path, task_id: str) -> list[str]:
    """Function to create command to run FLUKA."""
    input_file = next(dir_path.glob("*.inp"), None)
    if input_file is None:
        logging.debug("failed to generate fluka command. No *.inp file found in %s", dir_path)
        # if there is no input file, raise an error
        # this should never happen
        raise FileNotFoundError("Input file not found")

    # create settings object
    # we are providing input file, simulator type and additional options
    # provided option M with value 1 will run execute only one simulation cycle, default is 5
    settings = SimulationSettings(input_path=str(input_file), simulator_type=SimulatorType.fluka, cmdline_opts="-M 1")
    update_rng_seed_in_fluka_file(input_file, task_id)
    command_as_list = str(settings).split()
    command_as_list.append(str(input_file))
    return command_as_list


def update_rng_seed_in_fluka_file(input_file: Path, task_id: int) -> None:
    """Function to update random seed in FLUKA input file."""

    class UpdateFlukaRandomSeed(Protocol):
        """Definition of protocol for updating random seed in fluka input file.

        Its purpose is to allow us to use private method of Runner class.
        """

        def __call__(self, file_path: str, rng_seed: int) -> None:
            """Updates random seed in fluka input file"""

    random_seed = task_id
    update_fluka_function: UpdateFlukaRandomSeed = Runner._Runner__update_fluka_input_file  # pylint: disable=W0212
    update_fluka_function(str(input_file.resolve()), random_seed)


def execute_simulation_subprocess(dir_path: Path, command_as_list: list[str], celery_id: str,
                                  sim_type: str) -> tuple[bool, str, str]:
    """Function to execute simulation subprocess."""
    process_exit_success: bool = True
    command_stdout: str = ""
    command_stderr: str = ""
    state: str = ""
    try:
        process = subprocess.Popen(command_as_list,
                                   cwd=str(dir_path),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   text=True)
        try:
            # wait untill simulation subprocess is not marked in celery as ended
            while not state.get("end", False):
                time.sleep(1)
                # Check if the task has been marked to dump
                simulation = AsyncResult(celery_id)
                state = simulation.backend.get_task_meta(celery_id)
                if state.get("dump", False):
                    # Send SIGINT to the shieldhit subprocess to stop simulation and dump data
                    if sim_type == 'shieldhit':
                        os.kill(process.pid, signal.SIGINT)  # Only affects the subprocess, not the worker
                    # create rfluka file to stop fluka simulation and dump data
                    else:
                        FILE_NAME = 'rfluka.stop'
                        try:
                            if (target_folder := next(Path(dir_path).glob("fluka_*/"), None)):
                                (target_folder / FILE_NAME).write_text("")
                        except OSError as e:
                            logging.warning("Error due to file operation: %s", str(e))
                    # Wait for subprocess to finish and capture stdout and stderr
                    command_stdout, command_stderr = process.communicate()
                    break

        except Exception as e:
            logging.error("An error occurred: %s", e.stderr)

        logging.info("simulation subprocess with return code %d finished", process.returncode)

        process_exit_success = True

        # Log stdout and stderr using logging
        logging.info("Command Output:\n%s", command_stdout)
        logging.info("Command Error Output:\n%s", command_stderr)
    except subprocess.CalledProcessError as e:
        process_exit_success = False
        # If the command exits with a non-zero status
        logging.error("Command Error: %sSTD OUT: %s\nExecuted Command: %s", e.stderr, e.stdout,
                      " ".join(command_as_list))
    except Exception as e:  # skipcq: PYL-W0703
        process_exit_success = False
        logging.error("Exception while running simulation: %s", e)

    return process_exit_success, command_stdout, command_stderr


def get_fluka_estimators(dir_path: Path) -> dict:
    """Function to get estimators from FLUKA output files."""
    estimators_dict = {}

    matching_files = list(dir_path.glob("*_fort.*"))
    if len(matching_files) == 0:
        logging.error("No *_fort.* files found in %s", dir_path)
        return estimators_dict

    logging.debug("Found %d *_fort.* files in %s", len(matching_files), dir_path)
    files_pattern_pattern = str(dir_path / "*_fort.*")
    estimators_list = frompattern(pattern=files_pattern_pattern)
    for estimator in estimators_list:
        logging.debug("Appending estimator for %s", estimator.file_corename)
        for i, page in enumerate(estimator.pages):
            page.page_number = i

        estimators_dict[estimator.file_corename] = estimator

    return estimators_dict


def average_values(base_values: List[float], new_values: List[float], base_particles: int,
                   new_particles: int) -> List[float]:
    """Average two lists of values"""
    total_particles = base_particles + new_particles
    return [(base_val * base_particles + new_val * new_particles) / total_particles
            for base_val, new_val in zip(base_values, new_values)]


def average_estimators(base_list: list[dict], list_to_add: list[dict], total_particles: int,
                       new_particles: int) -> list:
    """Averages estimators from two dicts"""
    logging.debug("Averaging estimators - already averaged: %d", total_particles)
    for est_i, estimator_dict in enumerate(list_to_add):
        # check if estimator names are the same and if not, find matching estimator's index in base_list
        if estimator_dict["name"] != base_list[est_i]["name"]:
            est_i = next((i for i, item in enumerate(base_list) if item["name"] == estimator_dict["name"]), None)
        logging.debug("Averaging estimator %s", estimator_dict["name"])
        for page_i, page_dict in enumerate(estimator_dict["pages"]):
            # check if page numbers are the same and if not, find matching page's index in base_list
            if page_dict["metadata"]["page_number"] != base_list[est_i]["pages"][page_i]["metadata"]["page_number"]:
                page_i = next((i for i, item in enumerate(base_list[est_i]["pages"])
                               if item["metadata"]["page_number"] == page_dict["metadata"]["page_number"]), None)

            base_list[est_i]["pages"][page_i]["data"]["values"] = average_values(
                base_list[est_i]["pages"][page_i]["data"]["values"], page_dict["data"]["values"], total_particles,
                new_particles)

            logging.debug("Averaged page %s with %d elements", page_dict["metadata"]["page_number"],
                          len(page_dict["data"]["values"]))
    return base_list


def read_file(event: threading.Event,
              filepath: Path,
              simulation_id: int,
              task_id: str,
              update_key: str,
              celery_id: str,
              timeout_wait_for_file: int = 20,
              timeout_wait_for_line: int = 5 * 60,
              next_backend_update_time: int = 2,
              logging_level: int = logging.WARNING):
    """Monitors log file of certain task, when new line with message matching regex appears, sends update to backend"""
    logging.getLogger(__name__).setLevel(logging_level)
    logfile = None
    update_time = 0
    logging.info("Started monitoring, simulation id: %d, task id: %d", simulation_id, task_id)
    # if the logfile is not created in the first X seconds, it is probably an error
    for i in range(timeout_wait_for_file):  # maximum attempts, each attempt is one second
        if event.is_set():
            return
        try:
            logging.debug("Trying to open file %s, attempt %d/%d", filepath, i, timeout_wait_for_file)
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    # if logfile was not created in the first minute, task is marked as failed
    if logfile is None:
        logging.error("Log file for task %d not found", task_id)
        up_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
        send_task_update(simulation_id, task_id, update_key, up_dict)
        return
    logging.debug("Log file for task %d found", task_id)

    # create generator which waits for new lines in log file
    # if no new line appears in timeout_wait_for_line seconds, generator stops
    loglines = log_generator(logfile, event, timeout=timeout_wait_for_line)
    requested_primaries = 0
    logging.info("Parsing log file for task %d started", task_id)
    simulated_primaries = 0
    for line in loglines:
        if event.is_set():
            return
        utc_now = datetime.utcnow()
        logging.debug("Parsing line: %s", line.rstrip())
        if re.search(RUN_MATCH, line):
            logging.debug("Found RUN_MATCH in line: %s for file: %s and task: %d ", line.rstrip(), filepath, task_id)
            splitted = line.split()
            try:
                simulated_primaries = int(splitted[3])
            except (IndexError, ValueError):
                logging.error("Cannot parse number of simulated primaries in line: %s", line.rstrip())
            if (utc_now.timestamp() - update_time < next_backend_update_time  # do not send update too often
                    and requested_primaries >= simulated_primaries):
                logging.debug("Skipping update for task %d", task_id)
                continue
            update_time = utc_now.timestamp()
            estimated_seconds = 0
            try:
                estimated_seconds = int(splitted[9]) + int(splitted[7]) * 60 + int(splitted[5]) * 3600
            except (IndexError, ValueError):
                logging.error("Cannot parse estimated time in line: %s", line.rstrip())
            up_dict = {"simulated_primaries": simulated_primaries, "estimated_time": estimated_seconds}
            logging.debug("Sending update for task %d, simulated primaries %d", task_id, simulated_primaries)
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(REQUESTED_MATCH, line):
            logging.debug("Found REQUESTED_MATCH in line: %s for file: %s and task: %d ", line, filepath, task_id)
            # found a line with requested primaries, update database
            # task is in RUNNING state
            splitted = line.split(": ")
            requested_primaries = int(splitted[1])
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": requested_primaries,
                "start_time": utc_now.isoformat(sep=" "),
                "task_state": EntityState.RUNNING.value
            }
            logging.debug("Sending update for task %d, requested primaries %d", task_id, requested_primaries)
            send_task_update(simulation_id, task_id, update_key, up_dict)

        elif re.search(TIMEOUT_MATCH, line):
            logging.error("Simulation watcher %d timed out", task_id)
            up_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
            send_task_update(simulation_id, task_id, update_key, up_dict)
            return

        elif re.search(COMPLETE_MATCH, line):
            logging.debug("Found COMPLETE_MATCH in line: %s for file: %s and task: %d ", line, filepath, task_id)
            break
    logging.info("Parsing log file for task %d finished", task_id)
    up_dict = {
        "simulated_primaries": requested_primaries,
        "end_time": utc_now.isoformat(sep=" "),
        "task_state": EntityState.COMPLETED.value
    }
    logging.info("Sending final update for task %d, simulated primaries %d", task_id, simulated_primaries)
    send_task_update(simulation_id, task_id, update_key, up_dict)
    result = AsyncResult(celery_id)
    # mark celery task as ended to end a while loop waiting for results
    result.backend.store_result(celery_id, {"end": True}, state="RUNNING")


def read_fluka_file(event: threading.Event,
                    dirpath: Path,
                    simulation_id: int,
                    task_id: int,
                    update_key: str,
                    celery_id: str,
                    timeout_wait_for_file_s: int = 20,
                    timeout_wait_for_line_s: int = 5 * 60,
                    next_backend_update_time_s: int = 2,
                    logging_level: int = logging.WARNING):
    """Monitors log file of fluka task"""
    logging.getLogger(__name__).setLevel(logging_level)
    logfile = None
    logging.info("Started monitoring, simulation id: %d, task id: %d", simulation_id, task_id)

    # if the logfile is not created in the first X seconds, it is probably an error
    # continuation of awful glob path hack
    def get_first_matching_file() -> Optional[Path]:
        """Returns first matching file."""
        path = next(dirpath.glob("fluka_*/*001.out"), None)
        return path.resolve() if path else None

    for _ in range(timeout_wait_for_file_s):  # maximum attempts, each attempt is one second
        if event.is_set():
            return
        try:
            optional_file = get_first_matching_file()
            logging.info(optional_file)
            if not optional_file:
                time.sleep(1)
                continue
            logfile = open(optional_file)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    # if logfile was not created in the first minute, task is marked as failed
    if logfile is None:
        logging.error("Log file for task %d not found", task_id)
        up_dict = {"task_state": EntityState.FAILED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
        send_task_update(simulation_id, task_id, update_key, up_dict)
        return
    logging.debug("Log file for task %d found", task_id)

    # create generator which waits for new lines in log file
    # if no new line appears in timeout_wait_for_line seconds, generator stops
    loglines = log_generator(logfile, event, timeout=timeout_wait_for_line_s)
    logging.info("Parsing log file for task %d started", task_id)
    read_fluka_out_file(event,
                        loglines,
                        next_backend_update_time=next_backend_update_time_s,
                        details=TaskDetails(simulation_id, task_id, update_key),
                        verbose=logging_level <= logging.INFO)
    result = AsyncResult(celery_id)
    # mark celery task as ended to end a while loop waiting for results
    result.backend.store_result(celery_id, {"end": True}, state="RUNNING")


def read_file_offline(filepath: Path) -> tuple[int, int]:
    """Reads log file and returns number of simulated and requested primaries"""
    simulated_primaries = 0
    requested_primaries = 0
    try:
        with open(filepath, 'r') as f:
            for line in f:
                logging.debug("Parsing line: %s", line.rstrip())
                if re.search(RUN_MATCH, line):
                    logging.debug("Found RUN_MATCH in line: %s for file: %s", line.rstrip(), filepath)
                    splitted = line.split()
                    simulated_primaries = int(splitted[3])
                elif re.search(REQUESTED_MATCH, line):
                    logging.debug("Found REQUESTED_MATCH in line: %s for file: %s", line.rstrip(), filepath)
                    splitted = line.split(": ")
                    requested_primaries = int(splitted[1])
    except FileNotFoundError:
        logging.error("Log file %s not found", filepath)
    return simulated_primaries, requested_primaries
