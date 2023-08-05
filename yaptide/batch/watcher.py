import argparse
import re
import signal
import time
import json
from pathlib import Path
import urllib.request


RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"
TIMEOUT_MATCH = r"\bTimeout occured"
HARDCODED_BACKEND_URL = "https://yap-dev.c3.plgrid.pl/8443"


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


def send_task_update(simulation_id: int, task_id: str, update_key: str, update_dict: dict) -> bool:
    """Sends task update to flask to update database"""
    dict_to_send = {
        "simulation_id": simulation_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    tasks_url = HARDCODED_BACKEND_URL + "/tasks"
    try:
        req = urllib.request.Request(tasks_url, data=dict_to_send, method='POST')
        with urllib.request.urlopen(req) as res:
            if res.getcode() != 202:
                print("Task update for %s - Failed: %s", task_id, json.loads(res.read().decode('utf-8')))
                return False
    except Exception as e:
        print(e)
        return False
    return True


def read_file(filepath: Path, simulation_id: int, task_id: int, update_key: str):  # skipcq: PYL-W0613
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
        send_task_update(simulation_id=simulation_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
        print(f"Update for task: {task_id} - FAILED")
        return

    loglines = log_generator(logfile)
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
            send_task_update(simulation_id=simulation_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - simulated primaries: {splitted[3]}")

        elif re.search(REQUESTED_MATCH, line):
            splitted = line.split(": ")
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": "RUNNING"
            }
            send_task_update(simulation_id=simulation_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - RUNNING")

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
            send_task_update(simulation_id=simulation_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
            print(f"Update for task: {task_id} - COMPLETED")
            return

        elif re.search(TIMEOUT_MATCH, line):
            up_dict = {  # skipcq: PYL-W0612
                "task_state": "FAILED"
            }
            send_task_update(simulation_id=simulation_id, task_id=task_id, update_key=update_key, update_dict=up_dict)
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
