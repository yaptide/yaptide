from pathlib import Path
import re
import time
import argparse
import signal


def log_generator(thefile):
    """Generator equivalent to `tail -f` Linux command.
    Yields new lines appended to the end of the file.
    Main purpose is monitoring of the log files"""
    while True:
        line = thefile.readline()
        if not line:
            time.sleep(1)
            continue
        yield line


def read_file(filepath: Path, job_id: str, task_id: int):  # skipcq: PYL-W0613
    """Monitors log file of certain task"""
    run_match = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
    complete_match = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
    requested_match = r"\bRequested number of primaries NSTAT"

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
        print(f"Update for task: {task_id} - FAILED")
        return

    loglines = log_generator(logfile)
    for line in loglines:
        if re.search(run_match, line):
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": int(splitted[3]),
                "estimated_time": {
                    "hours": int(splitted[5]),
                    "minutes": int(splitted[7]),
                    "seconds": int(splitted[9]),
                }
            }
            print(f"Update for task: {task_id} - simulated primaries: {splitted[3]}")

        elif re.search(requested_match, line):
            splitted = line.split(": ")
            up_dict = {  # skipcq: PYL-W0612
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": "RUNNING"
            }
            print(f"Update for task: {task_id} - RUNNING")

        elif re.search(complete_match, line):
            splitted = line.split()
            up_dict = {  # skipcq: PYL-W0612
                "run_time": {
                    "hours": int(splitted[2]),
                    "minutes": int(splitted[4]),
                    "seconds": int(splitted[6]),
                },
                "task_state": "COMPLETED"
            }
            print(f"Update for task: {task_id} - COMPLETED")
            return


if __name__ == '__main__':
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument('--filepath', type=str)
    parser.add_argument('--job_id', type=str)
    parser.add_argument('--task_id', type=int)
    args = parser.parse_args()
    filepath_arg = Path(args.filepath)
    job_id_arg = args.job_id
    task_id_arg = args.task_id

    print(filepath=filepath_arg, job_id=job_id_arg, task_id=task_id_arg)

    read_file(filepath=filepath_arg, job_id=job_id_arg, task_id=task_id_arg)
