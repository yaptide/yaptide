import argparse
import logging
import time
import subprocess
from datetime import datetime

from pathlib import Path


def monitor_job(job_to_signal_id: int, root_dir: str, base_sleep_time: int):
    """"""
    get_state_command = f"sacct -j {job_to_signal_id} --format State | sed -n '3 p'"
    send_signal_command = f"scancel --signal=USR1 {job_to_signal_id}"
    wcl_command = f"wc -l {root_dir}/workspaces/task_*/stats.txt | grep -v total"

    # wait for the job to start
    while True:
        job_state = subprocess.getoutput(get_state_command).strip()

        if job_state == "PENDING":
            logging.info("Job %d is still pending", job_to_signal_id)
            time.sleep(1)
            continue

        if job_state == "RUNNING":
            logging.info("Job %d entered the RUNNING state", job_to_signal_id)
            break
        
        logging.info("Job %d state is %s - aborting monitoring", job_to_signal_id, job_state)
        return

    # monitor job
    next_sleep_time = base_sleep_time
    sent_signals = 0
    while True:
        logging.info("Next sleep will last %d seconds", next_sleep_time)
        time.sleep(next_sleep_time)

        job_state = subprocess.getoutput(get_state_command).strip()

        if job_state == "RUNNING":
            subprocess.getoutput(send_signal_command)
            sent_signals += 1
            logging.info("Sent SIGUSR1 to job: %d", job_to_signal_id)

            analysis_start_time = datetime.utcnow().timestamp()

            out = subprocess.getoutput(wcl_command)
            lengths = []
            filepaths = []
            for line in out.split("\n"):
                splitted = line.split()
                lengths.append(int(splitted[0]))
                filepaths.append(Path(splitted[1]))

            i = 0
            while len(lengths) * sent_signals > sum(lengths):
                logging.info("Waiting for all data")
                time.sleep(1)

                i+=1
                if i > 20:
                    break

                out = subprocess.getoutput(wcl_command)
                lengths = [int(line.split()[0]) for line in out.split("\n")]

            logging.info("All files have data")

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
    parser.add_argument("--base_sleep_time", type=int, default=30)

    args = parser.parse_args()

    root_dir_arg = args.root_dir
    job_to_signal_id_arg = args.job_to_signal_id
    base_sleep_time_arg = args.base_sleep_time

    monitor_job(
        job_to_signal_id=job_to_signal_id_arg,
        root_dir=root_dir_arg,
        base_sleep_time=base_sleep_time_arg
    )
