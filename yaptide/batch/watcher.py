import argparse
import logging
import re
import signal
import time

from pathlib import Path


RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
TIMEOUT_MATCH = r"\bTimeout occured"
ESTIMATOR_MATCH = r"\bEstimator\s*\d*\s*:\s*.*\s*with\s*\d*\s*page.*\b"
SAVING_ESTIMATOR_MATCH = r"\bSaving estimator to"
SAVING_END_MATCH = r"\bSaved all\s*\d*\s*estimator.*\b"


def log_generator(thefile, timeout: int = 3600) -> str:
    """
    Generator equivalent to `tail -f` Linux command.
    Yields new lines appended to the end of the file.
    Main purpose is monitoring of the log files
    """
    sleep_counter = 0
    while True:
        line = thefile.readline()
        if not line:
            time.sleep(1)
            sleep_counter += 1
            if sleep_counter >= timeout:
                return "Timeout occured"
            continue
        sleep_counter = 0
        yield line


def read_file(filepath: Path, job_id: str, task_id: int):  # skipcq: PYL-W0613
    """Monitors log file of certain task"""
    logfile = None
    for _ in range(30):  # 30 stands for maximum attempts
        try:
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    if logfile is None:
        up_dict = {  # skipcq: PYL-W0612
            "task_state": "FAILED"
        }
        logging.info("Update for task: %s - FAILED", task_id)
        return

    estimators_base_filenames = []
    # estimators_partial_filenames = []
    loglines = log_generator(logfile)
    saving_start_timestamp = None
    for line in loglines:
        if re.search(RUN_MATCH, line):
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": int(splitted[3]),
                "estimated_time": {
                    "hours": int(splitted[5]),
                    "minutes": int(splitted[7]),
                    "seconds": int(splitted[9]),
                }
            }
            logging.info("Update for task: %s - simulated primaries: %s", task_id, splitted[3])

        elif re.search(SAVING_ESTIMATOR_MATCH, line):
            if saving_start_timestamp is None:
                saving_start_timestamp = time.time()
                logging.info("Update for task: %s - saving start", task_id)
            splitted = line.split()

        elif re.search(ESTIMATOR_MATCH, line):
            splitted = line.split()
            estimators_base_filenames.append(splitted[3])
            logging.info("Update for task: %s - estimator: %s", task_id, splitted[3])

        elif re.search(SAVING_END_MATCH, line):
            if saving_start_timestamp is None:
                logging.info("Update for task: %s - saving end without start (cannot measure time)", task_id)
                continue
            saving_time = time.time() - saving_start_timestamp
            # reset saving_start_timestamp
            saving_start_timestamp = None
            # reset list of partial filenames
            estimators_partial_filenames = []
            logging.info("Update for task: %s - estimators saved in %f seconds", task_id, saving_time)

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": "RUNNING"
            }
            logging.info("Update for task: %s - RUNNING", task_id)

        elif re.search(COMPLETE_MATCH, line):
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "run_time": {
                    "hours": int(splitted[2]),
                    "minutes": int(splitted[4]),
                    "seconds": int(splitted[6]),
                },
                "task_state": "COMPLETED"
            }
            logging.info("Update for task: %s - COMPLETED", task_id)
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {  # skipcq: PYL-W0612
                "task_state": "FAILED"
            }
            logging.info("Update for task: %s - TIMEOUT", task_id)
            return
    return


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                        level=logging.INFO,
                        datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("--filepath", type=str)
    parser.add_argument("--job_id", type=str)
    parser.add_argument("--task_id", type=int)
    args = parser.parse_args()
    filepath_arg = Path(args.filepath)
    job_id_arg = args.job_id
    task_id_arg = args.task_id

    read_file(filepath=filepath_arg, job_id=job_id_arg, task_id=task_id_arg)
