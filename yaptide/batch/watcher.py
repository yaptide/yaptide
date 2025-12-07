import argparse
import json
import logging
import re
import signal
import ssl
import threading
import time
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from urllib import request
import yaptide.performance_tracker as tracker

RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
TIMEOUT_MATCH = r"\bTimeout occured"


def log_generator(thefile: TextIOWrapper, event: threading.Event = None, timeout: int = 3600) -> str:
    """
    Generator equivalent to `tail -f` Linux command.
    Yields new lines appended to the end of the file.
    It no new line appears in `timeout` seconds, generator stops.
    Main purpose is monitoring of the log files
    """
    sleep_counter = 0
    line_wait_id = None
    while True:
        if event and event.is_set():
            break
        if thefile is None:
            return "File not found"
        line = thefile.readline()
        if not line:

            if line_wait_id is None:
                line_wait_id = tracker.start("log_generator line wait")

            time.sleep(1)
            sleep_counter += 1
            if sleep_counter >= timeout:
                return "Timeout occured"
            continue
        sleep_counter = 0

        if line_wait_id is not None:
            tracker.end(line_wait_id)
            line_wait_id = None

        yield line


def send_task_update(sim_id: int, task_id: str, update_key: str, update_dict: dict, backend_url: str) -> bool:
    """Sends task update to flask to update database"""
    if not backend_url:
        logging.error("Backend url not specified")
        return False

    dict_to_send = {"simulation_id": sim_id, "task_id": task_id, "update_key": update_key, "update_dict": update_dict}
    tasks_url = f"{backend_url}/tasks"
    logging.debug("Sending update %s to the backend %s", dict_to_send, tasks_url)
    context = ssl.SSLContext()

    req = request.Request(tasks_url,
                          json.dumps(dict_to_send).encode(), {'Content-Type': 'application/json'},
                          method='POST')

    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update to %s failed", tasks_url)
                return False
    except Exception as e:  # skipcq: PYL-W0703
        print(e)
        logging.debug("Sending update to %s failed", tasks_url)
        return False
    return True


def read_file(filepath: Path, sim_id: int, task_id: int, update_key: str, backend_url: str):  # skipcq: PYL-W0613
    """Monitors log file of certain task"""
    logging.debug("Started monitoring, simulation id: %d, task id: %s", sim_id, task_id)
    logfile = None
    update_time = 0
    for _ in range(30):  # 30 stands for maximum attempts
        try:
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(1)

    if logfile is None:
        logging.debug("Log file for task %s not found", task_id)
        up_dict = {  # skipcq: PYL-W0612
            "task_state": "FAILED",
            "end_time": datetime.utcnow().isoformat(sep=" ")
        }
        send_task_update(sim_id=sim_id,
                         task_id=task_id,
                         update_key=update_key,
                         update_dict=up_dict,
                         backend_url=backend_url)
        logging.debug("Update for task: %d - FAILED", task_id)
        return

    loglines = log_generator(logfile, threading.Event())
    for line in loglines:
        utc_now = datetime.utcnow()
        if re.search(RUN_MATCH, line):
            logging.debug("Found RUN_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
            if utc_now.timestamp() - update_time < 2:  # hardcoded 2 seconds to avoid spamming
                logging.debug("Skipping update, too often")
                continue
            update_time = utc_now.timestamp()
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": int(splitted[3]),
                "estimated_time": int(splitted[9]) + int(splitted[7]) * 60 + int(splitted[5]) * 3600
            }
            send_task_update(sim_id=sim_id,
                             task_id=task_id,
                             update_key=update_key,
                             update_dict=up_dict,
                             backend_url=backend_url)
            logging.debug("Update for task: %d - simulated primaries: %s", task_id, splitted[3])

        elif re.search(REQUESTED_MATCH, line):
            logging.debug("Found REQUESTED_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
            splitted = line.split(": ")
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "start_time": utc_now.isoformat(sep=" "),
                "task_state": "RUNNING"
            }
            send_task_update(sim_id=sim_id,
                             task_id=task_id,
                             update_key=update_key,
                             update_dict=up_dict,
                             backend_url=backend_url)
            logging.debug("Update for task: %d - RUNNING", task_id)

        elif re.search(COMPLETE_MATCH, line):
            logging.debug("Found COMPLETE_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "end_time": utc_now.isoformat(sep=" "),
                "task_state": "COMPLETED"
            }
            send_task_update(sim_id=sim_id,
                             task_id=task_id,
                             update_key=update_key,
                             update_dict=up_dict,
                             backend_url=backend_url)
            logging.debug("Update for task: %d - COMPLETED", task_id)
            return

        elif re.search(TIMEOUT_MATCH, line):
            logging.debug("Found TIMEOUT_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
            up_dict = {  # skipcq: PYL-W0612
                "task_state": "FAILED",
                "end_time": datetime.utcnow().isoformat(sep=" ")
            }
            send_task_update(sim_id=sim_id,
                             task_id=task_id,
                             update_key=update_key,
                             update_dict=up_dict,
                             backend_url=backend_url)
            print("Update for task: %d - TIMEOUT", task_id)
            return
        else:
            logging.debug("No match found in line: %s for file: %s and task: %s ", line, filepath, task_id)
    return


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument("--filepath", type=str)
    parser.add_argument("--sim_id", type=int)
    parser.add_argument("--task_id", type=int)
    parser.add_argument("--update_key", type=str)
    parser.add_argument("--backend_url", type=str)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler()])

    logging.info("log file %s", args.filepath)
    logging.info("sim_id %s", args.sim_id)
    logging.info("task_id %s", args.task_id)
    logging.info("update_key %s", args.update_key)
    logging.info("backend_url %s", args.backend_url)
    read_file(filepath=Path(args.filepath),
              sim_id=args.sim_id,
              task_id=args.task_id,
              update_key=args.update_key,
              backend_url=args.backend_url)
