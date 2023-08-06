import argparse
import re
import signal
import time
import json
import ssl
from pathlib import Path
from urllib import request
import logging
from datetime import datetime


RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
TIMEOUT_MATCH = r"\bTimeout occured"
HARDCODED_BACKEND_URL = "https://yap-dev.c3.plgrid.pl:8443"


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


def send_task_update(sim_id: int, task_id: str, update_key: str, update_dict: dict) -> bool:
    """Sends task update to flask to update database"""
    dict_to_send = {
        "simulation_id": sim_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    tasks_url = f"{HARDCODED_BACKEND_URL}/tasks"
    context = ssl.SSLContext()

    req = request.Request(tasks_url,
                          json.dumps(dict_to_send).encode(),
                          {'Content-Type': 'application/json'},
                          method='POST')

    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update failed")
                return False
    except Exception as e:  # skipcq: PYL-W0703
        print(e)
        return False
    return True


def read_file(filepath: Path, sim_id: int, task_id: int, update_key: str):  # skipcq: PYL-W0613
    """Monitors log file of certain task"""
    logfile = None
    update_time = 0
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
        send_task_update(sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
        print(f"Update for task: {task_id} - FAILED")
        return

    loglines = log_generator(logfile)
    for line in loglines:
        utc_now = datetime.utcnow()
        if re.search(RUN_MATCH, line):
            if utc_now.timestamp() - update_time < 2:  # hardcoded 2 seconds to avoid spamming
                continue
            update_time = utc_now.timestamp()
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": int(splitted[3]),
                "estimated_time": int(splitted[9])
                + int(splitted[7]) * 60
                + int(splitted[5]) * 3600
            }
            send_task_update(sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - simulated primaries: {splitted[3]}")

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "start_time": utc_now.isoformat(sep=" "),
                "task_state": "RUNNING"
            }
            send_task_update(sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - RUNNING")

        elif re.search(COMPLETE_MATCH, line):
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "end_time": utc_now.isoformat(sep=" "),
                "task_state": "COMPLETED"
            }
            send_task_update(sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - COMPLETED")
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {  # skipcq: PYL-W0612
                "task_state": "FAILED"
            }
            send_task_update(sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - TIMEOUT")
            return
    return


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument("--filepath", type=str)
    parser.add_argument("--sim_id", type=int)
    parser.add_argument("--task_id", type=int)
    parser.add_argument("--update_key", type=str)
    args = parser.parse_args()
    filepath_arg = Path(args.filepath)
    sim_id_arg = args.sim_id
    task_id_arg = args.task_id
    update_key_arg = args.update_key

    print(filepath_arg, sim_id_arg, task_id_arg)

    read_file(filepath=filepath_arg, sim_id=sim_id_arg, task_id=task_id_arg, update_key=update_key_arg)
