import argparse
import json
import logging
import math
import numpy as np
import time
import subprocess
from datetime import datetime

from pathlib import Path

# wc -l /net/people/plgrid/plgpitrus/yaptide_tester/workspaces/task_*/stats.txt

def avg_and_std(values: list, weights: list) -> tuple[float, float]:
    avg = np.average(values, weights=weights)
    std = math.sqrt(np.average((values-avg)**2, weights=weights))
    return avg, std


def monitor_job(job_to_signal_id: int, root_dir: str, base_sleep_time: int):
    """"""
    get_state_command = f"sacct -j {job_to_signal_id} --format State | sed -n '3 p'"
    squeue_command = f"squeue -j {job_to_signal_id} -l"
    send_signal_command = f"scancel --signal=USR1 {job_to_signal_id}"
    kill_target_command = f"scancel {job_to_signal_id}"
    stat_files_pattern = "workspaces/task_*/stats.txt"
    wcl_command = f"wc -l {root_dir}/{stat_files_pattern} | grep -v total"
    root_path = Path(root_dir)
    global_stats = {}
    simulated_primaries = {}

    # wait for the job to start
    failed_attempts = 0
    while True:
        job_state = subprocess.getoutput(get_state_command).strip()

        if job_state == "PENDING":
            logging.info("Job %d is still pending", job_to_signal_id)
            continue

        if job_state == "RUNNING":
            logging.info("Job %d entered the RUNNING state", job_to_signal_id)
            break
        
        time.sleep(1)
        failed_attempts+=1
        if failed_attempts >= 10:
            logging.info("Job %d state is %s - aborting monitoring", job_to_signal_id, job_state)
            return
    squeue_out = subprocess.getoutput(squeue_command)
    logging.info("RUNNING count: %d", squeue_out.count("RUNNING"))
    logging.info("PENDING count: %d", squeue_out.count("PENDING"))
    logging.info("%s", squeue_out)

    # monitor job
    next_sleep_time = base_sleep_time
    sent_signals = 0
    while True:
        logging.info("Next sleep will last %d seconds", next_sleep_time)
        time.sleep(next_sleep_time)

        job_state = subprocess.getoutput(get_state_command).strip()
        squeue_out = subprocess.getoutput(squeue_command)
        running_tasks = squeue_out.count("RUNNING")
        pending_tasks = squeue_out.count("PENDING")

        if running_tasks > 0:
            # finish simulation with what we already have
            # some simulation tasks may get stuck without hope of proper ending
            # TODO: connect this with Waiting for all data
            # - if previous was not successful this may mean we have stuck simulation task
            if running_tasks < 5 and pending_tasks == 0:
                subprocess.getoutput(kill_target_command)
                break
            subprocess.getoutput(send_signal_command)
            sent_signals += 1
            analysis_start_time = datetime.utcnow().timestamp()
            logging.info("Sent SIGUSR1 to job: %d", job_to_signal_id)


            out = subprocess.getoutput(wcl_command)
            lengths = []
            filepaths = []
            for line in out.split("\n"):
                splitted = line.split()
                lengths.append(int(splitted[0]))
                filepaths.append(Path(splitted[1]))

            i = 0
            while len(lengths) > sum(lengths):
                logging.info("Waiting for all data")
                time.sleep(1)

                i+=1
                if i > 200:
                    logging.info("Breaking the waiting loop. Targeted number of lines: %d. Actually achieved: %d", len(lengths), sum(lengths))
                    break

                out = subprocess.getoutput(wcl_command)
                lengths = [int(line.split()[0]) for line in out.split("\n")]

            timestamps = []
            for stat_path in root_path.glob(stat_files_pattern):
                out = subprocess.getoutput(f"sed '1!d' {stat_path}")

                with open(stat_path, "w"):
                    pass

                try:
                    stat_dict: dict = json.loads(out)
                except json.decoder.JSONDecodeError:
                    continue

                task_id = stat_dict["task_id"]
                simulated_primaries[task_id] = stat_dict["simulated_primaries"]

                for detect_name in stat_dict.keys():
                    if detect_name == "finish_timestamp":
                        timestamps.append(stat_dict[detect_name] - analysis_start_time)
                        continue

                    if detect_name in ["task_id", "simulated_primaries"]:
                        continue

                    if detect_name not in global_stats:
                        global_stats[detect_name] = {}

                    for page in stat_dict[detect_name].keys():
                        if page not in global_stats[detect_name]:
                            global_stats[detect_name][page] = {}
                        global_stats[detect_name][page][task_id] = stat_dict[detect_name][page]

            std = np.std(timestamps)
            avg = np.average(timestamps)

            logging.info("Collected data: %d; Avg time from sending signal to end of saving: %f, std: %f", len(timestamps), avg, std)

            for file_name in global_stats.keys():
                file_stats = global_stats[file_name]
                for page in file_stats.keys():
                    page_stats = file_stats[page]
                    # for now values in analisys is 1-dimensional
                    values = []
                    weights = []
                    for task_id in page_stats.keys():
                        values.append(page_stats[task_id][0])
                        weights.append(simulated_primaries[task_id])
                    avg, std = avg_and_std(values=values, weights=weights)
                    std = np.std(values)
                    avg = np.average(values)
                    logging.info("Values for page %s are; average value %f; std %f ", page, avg, std)
            analysis_time = datetime.utcnow().timestamp() - analysis_start_time
            logging.info("Analisys took %f seconds", analysis_time)

            next_sleep_time = (base_sleep_time - int(analysis_time)
                               if base_sleep_time > int(analysis_time)
                               else 0)
            continue

        break


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                        level=logging.INFO,
                        datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("--root_dir", type=str)
    parser.add_argument("--job_to_signal_id", type=int)
    parser.add_argument("--base_sleep_time", type=int, default=300)

    args = parser.parse_args()

    root_dir_arg = args.root_dir
    job_to_signal_id_arg = args.job_to_signal_id
    base_sleep_time_arg = args.base_sleep_time

    monitor_job(
        job_to_signal_id=job_to_signal_id_arg,
        root_dir=root_dir_arg,
        base_sleep_time=base_sleep_time_arg
    )
