import argparse
from collections.abc import Iterator
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
from typing import Optional
from urllib import request
import math

import zmq

RUN_MATCH = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
COMPLETE_MATCH = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
REQUESTED_MATCH = r"\bRequested number of primaries NSTAT"


def log_generator(
    thefile: TextIOWrapper,
    event: threading.Event = None,
    max_idle_seconds: float = 3600,
    polling_interval_seconds: float = 1,
) -> Iterator[str]:
    """
    Generator equivalent to `tail -f` Linux command.
    Yields new lines appended to the end of the file.
    Main purpose is monitoring of the log files.

    Args:
        thefile: File object to read from.
        event: Threading event to signal when to stop the generator.
        max_idle_seconds: Maximum time to wait for new data before raising TimeoutError.
        polling_interval_seconds: Interval between successive file polls while no new data is available.
    """
    if thefile is None:
        raise ValueError("File object cannot be None.")
    idle_seconds = 0
    while True:
        if event and event.is_set():
            break
        line = thefile.readline()
        if not line:
            if event:
                if event.wait(polling_interval_seconds):
                    break
            else:
                time.sleep(polling_interval_seconds)
            idle_seconds += polling_interval_seconds
            if idle_seconds >= max_idle_seconds:
                raise TimeoutError("No new log data received before timeout.")
            continue
        idle_seconds = 0
        yield line


def send_task_update(sim_id: int, task_id: int, update_key: str, update_dict: dict, backend_url: str) -> bool:
    """Sends task update to the aggregator, or directly to flask when no aggregator is reachable"""
    global AGGREGATOR_SENDER  # skipcq: PYL-W0603
    if AGGREGATOR_SENDER is None:
        # the aggregator runs in its own job, it may still have been queued when this task started
        AGGREGATOR_SENDER = connect_to_aggregator(AGGREGATOR_AUTH_PATH, update_key)
    if AGGREGATOR_SENDER is not None and AGGREGATOR_SENDER.send(task_id=task_id, update_dict=update_dict):
        return True
    # without the aggregator hundreds of tasks talk to flask directly - the load that made it unresponsive,
    # so state changes always go through, progress alone is throttled (only where an aggregator is expected)
    now = time.monotonic()
    if AGGREGATOR_AUTH_PATH is not None and "task_state" not in update_dict:
        if now - REST_FALLBACK["last_progress_seconds"] < REST_FALLBACK_PROGRESS_INTERVAL_SECONDS:
            logging.debug("No aggregator, skipping progress update for task %d", task_id)
            return True
        REST_FALLBACK["last_progress_seconds"] = now
    return post_task_update(
        sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=update_dict, backend_url=backend_url
    )


def post_task_update(sim_id: int, task_id: int, update_key: str, update_dict: dict, backend_url: str) -> bool:
    """Sends task update to flask to update database"""
    if not backend_url:
        logging.error("Backend url not specified")
        return False

    dict_to_send = {"simulation_id": sim_id, "task_id": task_id, "update_key": update_key, "update_dict": update_dict}
    tasks_url = f"{backend_url}/tasks"
    logging.debug("Sending update %s to the backend %s", dict_to_send, tasks_url)
    context = ssl.SSLContext()

    req = request.Request(
        tasks_url, json.dumps(dict_to_send).encode(), {"Content-Type": "application/json"}, method="POST"
    )

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


class AggregatorSender:
    """Pushes task updates to the aggregator of the simulation over a persistent ZeroMQ socket"""

    def __init__(self, auth_path: Path, update_key: str):
        auth = json.loads(auth_path.read_text())
        self.update_key = update_key
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUSH)
        # a dead aggregator must fail the send instead of silently queueing - the REST fallback then takes over,
        # so messages are queued only to a live connection and just a handful of them
        self.socket.setsockopt(zmq.IMMEDIATE, 1)
        self.socket.setsockopt(zmq.SNDHWM, 100)
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.connect(f"tcp://{auth['host']}:{auth['port']}")
        logging.debug("Connected to aggregator at %s:%s", auth["host"], auth["port"])

    def send(self, task_id: int, update_dict: dict) -> bool:
        """Returns False when the update could not be handed over to the aggregator"""
        message = {"update_key": self.update_key, "task_id": task_id, "update_dict": update_dict}
        try:
            self.socket.send(json.dumps(message).encode(), flags=zmq.NOBLOCK)
        except zmq.ZMQError as e:
            logging.warning("Sending update to the aggregator failed: %s", e)
            return False
        return True


def connect_to_aggregator(auth_path: Optional[Path], update_key: str) -> Optional[AggregatorSender]:
    """Builds the sender, returns None when no aggregator is available and REST should be used instead"""
    if auth_path is None or not auth_path.exists():
        return None
    try:
        return AggregatorSender(auth_path=auth_path, update_key=update_key)
    except Exception as e:  # skipcq: PYL-W0703
        logging.warning("Could not connect to the aggregator described by %s: %s", auth_path, e)
        return None


AGGREGATOR_AUTH_PATH: Optional[Path] = None
AGGREGATOR_SENDER: Optional[AggregatorSender] = None
REST_FALLBACK_PROGRESS_INTERVAL_SECONDS = 30
REST_FALLBACK = {"last_progress_seconds": 0.0}


def read_shieldhit_file(
    filepath: Path,
    sim_id: int,
    task_id: int,
    update_key: str,
    backend_url: str,
    max_wait_for_file_seconds: float = 30,
    max_idle_seconds: float = 3600,
    update_interval_seconds: float = 2,
    polling_interval_seconds: float = 1,
):  # skipcq: PYL-W0613
    """
    Monitors log file of a shieldhit task and sends updates to the backend.
    The purpose of the updates is the progress bar update and state updates
    (like simulation failed or completed). All possible exceptions are caught and logged,
    and in case of any exception the task is marked as FAILED.

    Args:
        filepath: Path to the log file to monitor.
        sim_id: Simulation ID.
        task_id: Task ID.
        update_key: Simulation auth token for backend updates.
        backend_url: URL of the backend server to send updates to.
        max_wait_for_file_seconds: Maximum time to wait for the log file to be created
            before marking the task as FAILED.
        max_idle_seconds: Maximum time to wait for new data before marking the task as FAILED.
        update_interval_seconds: Minimum interval between successive updates to the backend.
        polling_interval_seconds: Interval between successive file polls while no new
            data is available or while waiting for the file to be created.
    """
    try:
        logging.debug("Started monitoring, simulation id: %d, task id: %s", sim_id, task_id)
        logfile = None
        last_update_timestamp_seconds = 0

        open_file_attempts = math.ceil(max_wait_for_file_seconds / polling_interval_seconds)
        for _ in range(open_file_attempts):
            try:
                logfile = open(filepath)  # skipcq: PTC-W6004
                break
            except FileNotFoundError:
                time.sleep(polling_interval_seconds)

        if logfile is None:
            logging.debug("Log file for task %s not found", task_id)
            up_dict = {  # skipcq: PYL-W0612
                "task_state": "FAILED",
                "end_time": datetime.utcnow().isoformat(sep=" "),
            }
            send_task_update(
                sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
            )
            logging.debug("Update for task: %d - FAILED", task_id)
            return

        loglines = log_generator(
            logfile,
            threading.Event(),
            max_idle_seconds=max_idle_seconds,
            polling_interval_seconds=polling_interval_seconds,
        )

        for line in loglines:
            utc_now = datetime.utcnow()
            if re.search(RUN_MATCH, line):
                logging.debug("Found RUN_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
                if utc_now.timestamp() - last_update_timestamp_seconds < update_interval_seconds:
                    logging.debug("Skipping update, too often")
                    continue
                last_update_timestamp_seconds = utc_now.timestamp()
                splitted = line.split()
                up_dict = {  # skipcq: PYL-W0612
                    "simulated_primaries": int(splitted[3]),
                    "estimated_time": int(splitted[9]) + int(splitted[7]) * 60 + int(splitted[5]) * 3600,
                }
                send_task_update(
                    sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
                )
                logging.debug("Update for task: %d - simulated primaries: %s", task_id, splitted[3])

            elif re.search(REQUESTED_MATCH, line):
                logging.debug("Found REQUESTED_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
                splitted = line.split(": ")
                up_dict = {  # skipcq: PYL-W0612
                    "simulated_primaries": 0,
                    "requested_primaries": int(splitted[1]),
                    "start_time": utc_now.isoformat(sep=" "),
                    "task_state": "RUNNING",
                }
                send_task_update(
                    sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
                )
                logging.debug("Update for task: %d - RUNNING", task_id)

            elif re.search(COMPLETE_MATCH, line):
                logging.debug("Found COMPLETE_MATCH in line: %s for file: %s and task: %s ", line, filepath, task_id)
                up_dict = {  # skipcq: PYL-W0612
                    "end_time": utc_now.isoformat(sep=" "),
                    "task_state": "COMPLETED",
                }
                send_task_update(
                    sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
                )
                logging.debug("Update for task: %d - COMPLETED", task_id)
                return
            else:
                logging.debug("No match found in line: %s for file: %s and task: %s ", line, filepath, task_id)

        raise RuntimeError(
            f"Log stream ended without completion markers in SHIELDHIT monitor for task {task_id}. "
            f"This should never happen."
        )
    except TimeoutError as err:
        logging.warning("Log monitoring timed out for file %s and task %s: %s", filepath, task_id, err)
        up_dict = {  # skipcq: PYL-W0612
            "task_state": "FAILED",
            "end_time": datetime.utcnow().isoformat(sep=" "),
        }
        send_task_update(
            sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
        )
        logging.debug("Update for task: %d - TIMEOUT", task_id)
    except Exception as err:
        logging.error("Error while monitoring log file %s for task %s: %s", filepath, task_id, err)
        up_dict = {  # skipcq: PYL-W0612
            "task_state": "FAILED",
            "end_time": datetime.utcnow().isoformat(sep=" "),
        }
        send_task_update(
            sim_id=sim_id, task_id=task_id, update_key=update_key, update_dict=up_dict, backend_url=backend_url
        )
        logging.debug("Update for task: %d - ERROR", task_id)
    finally:
        if logfile is not None:
            logfile.close()


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument("--filepath", type=str)
    parser.add_argument("--sim_id", type=int)
    parser.add_argument("--task_id", type=int)
    parser.add_argument("--update_key", type=str)
    parser.add_argument("--backend_url", type=str)
    parser.add_argument("--zmq_auth", type=str, default=None, help="path to the .zmq_auth file of the aggregator")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    logging.basicConfig(
        level=log_level, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler()]
    )

    logging.info("log file %s", args.filepath)
    logging.info("sim_id %s", args.sim_id)
    logging.info("task_id %s", args.task_id)
    logging.info("update_key %s", args.update_key)
    logging.info("backend_url %s", args.backend_url)
    AGGREGATOR_AUTH_PATH = Path(args.zmq_auth) if args.zmq_auth else None
    AGGREGATOR_SENDER = connect_to_aggregator(AGGREGATOR_AUTH_PATH, args.update_key)
    read_shieldhit_file(
        filepath=Path(args.filepath),
        sim_id=args.sim_id,
        task_id=args.task_id,
        update_key=args.update_key,
        backend_url=args.backend_url,
    )
