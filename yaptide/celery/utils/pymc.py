import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from pymchelper.executor.options import SimulationSettings
from pymchelper.input_output import frompattern

from yaptide.batch.watcher import (COMPLETE_MATCH, REQUESTED_MATCH, RUN_MATCH,
                                   TIMEOUT_MATCH, log_generator)
from yaptide.celery.utils.requests import send_task_update
from yaptide.utils.enums import EntityState


def command_to_run_shieldhit(dir_path: Path, task_id: str) -> list[str]:
    settings = SimulationSettings(input_path=dir_path,  # skipcq: PYL-W0612 # usefull
                                  simulator_exec_path=None,  # useless, we guess from PATH
                                  cmdline_opts="")  # useless, we could use -q in the future
    # last part of task_id gives an integer seed for random number generator
    settings.set_rng_seed(int(task_id.split("_")[-1]))
    command_as_list = str(settings).split()
    command_as_list.append(str(dir_path))
    return command_as_list

def execute_shieldhit_process(dir_path: Path, command_as_list: list[str]) -> tuple[bool, str, str]:
    process_exit_success : bool = True
    command_stdout: str = ""
    command_stderr: str = ""
    try:
        # If check=True and the exit code is non-zero, raises a
        # CalledProcessError (has return code and output/error streams).
        # text=True means stdout and stderr will be strings instead of bytes
        logging.info("Starting SHIELD-HIT12A subprocess")
        completed_process = subprocess.run(command_as_list,
                                           check=True,
                                           cwd=str(dir_path),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           text=True)
        logging.info("SHIELD-HIT12A subprocess with return code %d finished", completed_process.returncode)

        # Capture stdout and stderr
        command_stdout = completed_process.stdout
        command_stderr = completed_process.stderr

        process_exit_success = True

        # Log stdout and stderr using logging
        logging.info("Command Output:\n%s", command_stdout)
        logging.info("Command Error Output:\n%s", command_stderr)
    except subprocess.CalledProcessError as e:
        process_exit_success = False
        # If the command exits with a non-zero status
        logging.error("Command Error: %s\nExecuted Command: %s", e.stderr, " ".join(command_as_list))
    except Exception as e:  # skipcq: PYL-W0703
        process_exit_success = False
        logging.error("Exception while running SHIELD-HIT12A: %s", e)

    return process_exit_success, command_stdout, command_stderr


def get_shieldhit_estimators(dir_path: Path) -> dict:
    estimators_dict = {}

    matching_files = list(dir_path.glob("*.bdo"))
    if len(matching_files) == 0:
        logging.error("No *.bdo files found in %s", dir_path)
        return estimators_dict
    else:
        logging.debug("Found %d *.bdo files in %s", len(matching_files), dir_path)
        files_pattern_pattern = str(dir_path / "*.bdo")
        estimators_list = frompattern(pattern=files_pattern_pattern)
        for estimator in estimators_list:
            logging.debug("Appending estimator for %s", estimator.file_corename)
            estimators_dict[estimator.file_corename] = estimator

    return estimators_dict

# def run_shieldhit(dir_path: Path, task_id: str) -> dict:
#     """Function to run single SHIELD-HIT12A simulation"""
#     logging.info("Running SHIELD-HIT12A with command: %s", " ".join(command_as_list))

#     simulation_failed : bool = False

#     try:
#         # If check=True and the exit code is non-zero, raises a
#         # CalledProcessError (has return code and output/error streams).
#         # text=True means stdout and stderr will be strings instead of bytes
#         logging.info("Starting SHIELD-HIT12A subprocess for task %s", task_id)
#         time.sleep(1)
#         completed_process = subprocess.run(command_as_list,
#                                            check=True,
#                                            cwd=str(dir_path),
#                                            stdout=subprocess.PIPE,
#                                            stderr=subprocess.PIPE,
#                                            text=True)
#         logging.info("SHIELD-HIT12A subprocess with return code %d finished", completed_process.returncode)

#         # Capture stdout and stderr
#         command_stdout = completed_process.stdout
#         command_stderr = completed_process.stderr

#         simulation_failed = False

#         # Log stdout and stderr using logging
#         logging.info("Command Output:\n%s", command_stdout)
#         logging.info("Command Error Output:\n%s", command_stderr)
#     except subprocess.CalledProcessError as e:
#         simulation_failed = True
#         # If the command exits with a non-zero status
#         logging.error("Command Error: %s\nExecuted Command: %s", e.stderr, " ".join(command_as_list))
#     except Exception as e:  # skipcq: PYL-W0703
#         simulation_failed = True
#         logging.error("Exception while running SHIELD-HIT12A: %s", e)

#     logging.info("SHIELD-HIT12A simulation for task %s finished", task_id)
#     logging.debug("Simulation failed: %s", simulation_failed)

#     estimators_dict = {}
#     files_pattern_pattern = str(dir_path / "*.bdo")
#     estimators_list = frompattern(files_pattern_pattern)
#     for estimator in estimators_list:
#         logging.debug("Appending estimator for %s", estimator.file_corename)
#         estimators_dict[estimator.file_corename] = estimator

#     return estimators_dict


def average_estimators(base_list: list[dict], list_to_add: list[dict], averaged_count: int) -> list:
    """Averages estimators from two dicts"""
    logging.debug("Averaging estimators - already averaged: %d", averaged_count)
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

            base_list[est_i]["pages"][page_i]["data"]["values"] = [
                sum(x) / (averaged_count + 1) for x in zip(
                    map(lambda x: x * averaged_count, base_list[est_i]["pages"][page_i]["data"]["values"]),
                    page_dict["data"]["values"]
                )
            ]
            logging.debug("Averaged page %s with %d elements",
                          page_dict["metadata"]["page_number"],
                          len(page_dict["data"]["values"]))
    return base_list


def read_file(filepath: Path,
              simulation_id: int,
              task_id: str,
              update_key: str,
              timeout_wait_for_file: int = 15,
              timeout_wait_for_line: int = 5*60,
              next_backend_update_time: int = 2,
              logging_level: int = logging.WARNING):
    """Monitors log file of certain task"""
    logging.getLogger(__name__).setLevel(logging_level)
    logfile = None
    update_time = 0
    logging.info("Started monitoring, simulation id: %d, task id: %s", simulation_id, task_id)
    # if the logfile is not created in the first X seconds, it is probably an error
    for i in range(timeout_wait_for_file):  # maximum attempts, each attempt is one second
        try:
            logging.debug("Trying to open file %s, attempt %d/%d", filepath, i, timeout_wait_for_file)
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    # # if logfile was not created in the first minute, task is marked as failed
    # if logfile is None:
    #     logging.error("Log file for task %s not found", task_id)
    #     up_dict = {
    #         "task_state": EntityState.FAILED.value,
    #         "end_time": datetime.utcnow().isoformat(sep=" ")
    #     }
    #     send_task_update(simulation_id, task_id, update_key, up_dict)
    #     return
    # logging.debug("Log file for task %s found", task_id)

    # # create generator which waits for new lines in log file
    # # if no new line appears in timeout_wait_for_line seconds, generator stops
    # loglines = log_generator(logfile, timeout=timeout_wait_for_line)
    # requested_primaries = 0
    # logging.info("Parsing log file for task %s started", task_id)
    # for line in loglines:
    #     utc_now = datetime.utcnow()
    #     if re.search(RUN_MATCH, line):
    #         logging.debug("Found RUN_MATCH in line: %s for file: %s and task: %s ", line.rstrip(), filepath, task_id)
    #         splitted = line.split()
    #         simulated_primaries = int(splitted[3])
    #         if (utc_now.timestamp() - update_time < next_backend_update_time  # do not send update too often
    #                 and requested_primaries > simulated_primaries):
    #             logging.debug("Skipping update for task %s", task_id)
    #             continue
    #         update_time = utc_now.timestamp()
    #         up_dict = {
    #             "simulated_primaries": simulated_primaries,
    #             "estimated_time": int(splitted[9])
    #             + int(splitted[7]) * 60
    #             + int(splitted[5]) * 3600
    #         }
    #         logging.debug("Sending update for task %s, simulated primaries %d", task_id, simulated_primaries)
    #         send_task_update(simulation_id, task_id, update_key, up_dict)

    #     elif re.search(REQUESTED_MATCH, line):
    #         logging.debug("Found REQUESTED_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
    #         # found a line with requested primaries, update database
    #         # task is in RUNNING state
    #         splitted = line.split(": ")
    #         requested_primaries = int(splitted[1])
    #         up_dict = {
    #             "simulated_primaries": 0,
    #             "requested_primaries": requested_primaries,
    #             "start_time": utc_now.isoformat(sep=" "),
    #             "task_state": EntityState.RUNNING.value
    #         }
    #         logging.debug("Sending update for task %s, requested primaries %d", task_id, requested_primaries)
    #         send_task_update(simulation_id, task_id, update_key, up_dict)

    #     elif re.search(TIMEOUT_MATCH, line):
    #         logging.error("Simulation watcher %s timed out", task_id)
    #         up_dict = {
    #             "task_state": EntityState.FAILED.value,
    #             "end_time": datetime.utcnow().isoformat(sep=" ")
    #         }
    #         send_task_update(simulation_id, task_id, update_key, up_dict)
    #         return

    #     elif re.search(COMPLETE_MATCH, line):
    #         logging.debug("Found COMPLETE_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
    #         break

    # logging.info("Parsing log file for task %s finished", task_id)
    # up_dict = {
    #     "simulated_primaries": requested_primaries,
    #     "end_time": utc_now.isoformat(sep=" "),
    #     "task_state": EntityState.COMPLETED.value
    # }
    # logging.info("Sending final update for task %s, simulated primaries %d", task_id, simulated_primaries)
    # send_task_update(simulation_id, task_id, update_key, up_dict)
