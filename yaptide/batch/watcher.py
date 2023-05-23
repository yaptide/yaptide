import argparse
import json
import logging
import re
import signal
import subprocess
import time

from datetime import datetime
from pathlib import Path


RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
TIMEOUT_MATCH = r"\bTimeout occured"
ESTIMATOR_MATCH = r"\bEstimator\s*\d*\s*:\s*.*\s*with\s*\d*\s*page.*\b"
SAVING_ESTIMATOR_MATCH = r"\bSaving estimator to"
SAVING_END_MATCH = r"\bSaved all\s*\d*\s*estimator.*\b"
SIGNAL_MATCH = r"Caught SIGUSR1. Saving data."


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


def change_date_to_phrase_in_name(old_name: str, phrase_to_insert: str) -> str:
    """Removes date in isoformat and inserts provided phrase in the provided name"""
    name_parts = old_name.split("_")
    ending = name_parts[-1]
    name_parts = name_parts[:-3]
    name_parts.append(phrase_to_insert)
    name_parts.append(ending)
    new_name_base = "_".join(name_parts)
    return new_name_base


def get_page(page_number: str, json_obj: dict):
    try:
        for page in json_obj["pages"]:
            if page["metadata"]["page_number"] == page_number:
                return page
    except:
        pass
    return None


def read_file(filepath: Path, workdir: Path, convertmc: str, job_id: str, task_id: int):  # skipcq: PYL-W0613
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

    statspath = workdir / "stats.txt"
    with open(statspath, 'a') as writer:
        writer.write("")

    confpath = workdir / "watcher_conf.json"
    with open(confpath, "r") as reader:
        observables: dict = json.load(reader)

    estimators_filenames_patterns: list[str] = []
    estimators_filepaths: list[str] = []
    loglines = log_generator(logfile)
    saving_start_timestamp = None
    signals_caught = 0
    simulated_primaries = 0
    for line in loglines:
        if re.search(RUN_MATCH, line):
            splitted = line.split()
            simulated_primaries = int(splitted[3])
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": simulated_primaries,
                "estimated_time": {
                    "hours": int(splitted[5]),
                    "minutes": int(splitted[7]),
                    "seconds": int(splitted[9]),
                }
            }
            logging.info("Update for task: %s - simulated primaries: %s", task_id, simulated_primaries)

        elif re.search(SAVING_ESTIMATOR_MATCH, line):
            if saving_start_timestamp is None:
                logging.info("Update for task: %s - final saving start", task_id)
            splitted = line.split()
            filepath_str = splitted[3].replace("'", "")
            estimators_filepaths.append(filepath_str)

        elif re.search(SIGNAL_MATCH, line):
            saving_start_timestamp = datetime.utcnow().timestamp()
            signals_caught+=1
            logging.info("Update for task: %s - saving start", task_id)

        elif re.search(ESTIMATOR_MATCH, line):
            splitted = line.split()
            # new_name_base = change_date_to_phrase_in_name(splitted[3], "\d*")
            estimators_filenames_patterns.append(splitted[3])
            logging.info("Update for task: %s - estimator: %s", task_id, splitted[3])

        elif re.search(SAVING_END_MATCH, line):
            phrase_to_insert = ("final"
                                if saving_start_timestamp is None
                                else str(signals_caught))
            data_to_write = {}
            for filepath_str in estimators_filepaths:
                splitted_filepath = filepath_str.split("/")
                filename = splitted_filepath[-1]

                # we want to enter name changing block if file is observable
                # or if it is final round of saving at the end of simulation
                filename_base = "_".join(filename.split("_")[:-3])
                if (filename_base in observables
                    or saving_start_timestamp is None):
                    # we rename observable files and final results 
                    new_filename = change_date_to_phrase_in_name(filename, phrase_to_insert)
                    splitted_filepath[-1] = new_filename
                    new_filepath_str = "/".join(splitted_filepath)

                    subprocess.run(["mv", filepath_str, new_filepath_str])
                    filepath_str = new_filepath_str

                    # we want to convert the file only if it is not final result
                    if saving_start_timestamp is not None:
                        data_to_write[filename_base] = {}
                        subprocess.run([convertmc, "json", filepath_str])
                        json_path = workdir / "_".join([filename_base, str(signals_caught), ".json"])
                        with open(json_path, 'r') as reader:
                            json_obj = json.load(reader)
                        subprocess.run(["rm", json_path])

                        for page_number in observables[filename_base].keys():
                            # page_number = str(observable["page_number"])
                            page = get_page(page_number, json_obj)
                            if page is None:
                                logging.info("Page %s not found", page_number)
                                continue
                            data_to_write[filename_base][page_number] = [
                                page["data"]["values"][idx] for idx in observables[filename_base][page_number]["target_idxs"]
                            ]

            if saving_start_timestamp is not None:
                # we want to remove unnecessary file (results are necessary)
                subprocess.run(["rm", f"{workdir}/*.bdo"])
                utc_now = datetime.utcnow().timestamp()
                data_to_write["task_id"] = task_id
                data_to_write["simulated_primaries"] = simulated_primaries
                data_to_write["finish_timestamp"] = utc_now
                with open(statspath, 'a') as writer:
                    writer.write(json.dumps(data_to_write))
                    writer.write("\n")
                estimators_filepaths = []
                saving_time = datetime.utcnow().timestamp() - saving_start_timestamp
                # reset saving_start_timestamp
                saving_start_timestamp = None
                # reset list of partial filenames
                logging.info("Update for task: %s - estimators saved in %f seconds", task_id, saving_time)
                continue
            else:
                # remove stats file at the end of job
                subprocess.run(["rm", statspath])
            logging.info("Update for task: %s - final saving end", task_id)

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
    parser.add_argument("--workdir", type=str)
    parser.add_argument("--convertmc", type=str)
    parser.add_argument("--filepath", type=str)
    parser.add_argument("--job_id", type=str)
    parser.add_argument("--task_id", type=int)
    args = parser.parse_args()
    workdir_arg = Path(args.workdir)
    convertmc_arg = args.convertmc
    filepath_arg = Path(args.filepath)
    job_id_arg = args.job_id
    task_id_arg = args.task_id

    read_file(filepath=filepath_arg, workdir=workdir_arg, convertmc=convertmc_arg, job_id=job_id_arg, task_id=task_id_arg)
