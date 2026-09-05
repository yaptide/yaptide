"""Collects task updates from the watchers of a single simulation and forwards them to the backend in batches.

One aggregator runs per submitted simulation, in its own small SLURM allocation - never on the login node,
where a process living as long as the simulation would be killed by the site policy.
Watchers running inside the array tasks push their updates over ZeroMQ (cluster internal network)
instead of calling the backend directly - with hundreds of tasks the REST calls made Flask unresponsive.
"""

import argparse
import json
import logging
import os
import secrets
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Optional
from urllib import request
from urllib.error import HTTPError

import zmq

DEFAULT_INTERFACE = "ib0"
DEFAULT_FLUSH_INTERVAL_SECONDS = 10
DEFAULT_IDLE_TIMEOUT_SECONDS = 3600
BACKEND_TIMEOUT_SECONDS = 30
FINAL_FLUSH_DEADLINE_SECONDS = 300
TERMINAL_TASK_STATES = {"COMPLETED", "FAILED", "CANCELED"}
AUTH_FILE_NAME = ".zmq_auth"
SIOCGIFADDR = 0x8915


def interface_ip(interface: str) -> Optional[str]:
    """IPv4 address of the given network interface, None if the interface does not exist"""
    try:
        import fcntl  # skipcq: PYL-C0415
        import struct  # skipcq: PYL-C0415

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            packed = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, struct.pack("256s", interface.encode()[:15]))
    except (ImportError, OSError):  # no fcntl on windows, no such interface on linux
        logging.warning("Interface %s not available", interface)
        return None
    return socket.inet_ntoa(packed[20:24])


def advertised_ip(interface: str) -> str:
    """Address the watchers connect to - the cluster internal network, with a fallback for machines without it"""
    return interface_ip(interface) or socket.gethostbyname(socket.gethostname())


def write_auth_file(auth_path: Path, host: str, port: int, secret: str) -> None:
    """Writes connection details for the watchers, readable only by the owner of the simulation.

    Written to a temporary file first, so a watcher on another node never reads a half written file.
    """
    tmp_path = auth_path.with_suffix(".tmp")
    tmp_path.touch(mode=0o600)
    tmp_path.chmod(0o600)
    tmp_path.write_text(json.dumps({"host": host, "port": port, "secret": secret}))
    os.replace(tmp_path, auth_path)


class TaskUpdateAggregator:
    """Receives task updates over a ZeroMQ PULL socket and posts them to the backend in batches"""

    def __init__(  # skipcq: PYL-R0913
        self,
        sim_id: int,
        update_key: str,
        backend_url: str,
        root_dir: Path,
        ntasks: int,
        interface: str = DEFAULT_INTERFACE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
    ):
        self.sim_id = sim_id
        self.update_key = update_key
        self.backend_url = backend_url
        self.root_dir = root_dir
        self.ntasks = ntasks
        self.interface = interface
        self.flush_interval_seconds = flush_interval_seconds
        self.idle_timeout_seconds = idle_timeout_seconds

        self.secret = secrets.token_hex(32)
        self.stop_event = threading.Event()
        self._pending: dict[int, dict] = {}
        self._finished_tasks: set[int] = set()

    def store_update(self, task_id: int, update_dict: dict) -> None:
        """Merges an update into the pending batch, newer values overwrite older ones"""
        self._pending.setdefault(task_id, {}).update(update_dict)
        if update_dict.get("task_state") in TERMINAL_TASK_STATES:
            self._finished_tasks.add(task_id)

    def all_tasks_finished(self) -> bool:
        """True once every task of the simulation reported a terminal state"""
        return len(self._finished_tasks) >= self.ntasks

    def flush(self) -> None:
        """Sends everything collected so far as a single bulk update"""
        batch, self._pending = self._pending, {}
        if not batch:
            return

        payload = {
            "simulation_id": self.sim_id,
            "update_key": self.update_key,
            "tasks": [{"task_id": task_id, "update_dict": update_dict} for task_id, update_dict in batch.items()],
        }
        if self.send_bulk_update(payload):
            logging.debug("Sent updates for %d tasks", len(batch))
            return

        # keep the updates for the next flush, values received in the meantime are newer and win
        for task_id, update_dict in batch.items():
            self._pending[task_id] = {**update_dict, **self._pending.get(task_id, {})}

    def send_bulk_update(self, payload: dict) -> bool:
        """Posts the batch to the backend.

        Returns True when the batch is done with - accepted, or rejected as invalid (4xx), because
        retrying an invalid batch would only block every later update of the simulation.
        Returns False when the backend could not be reached or failed (5xx), so the batch is retried.
        """
        bulk_url = f"{self.backend_url}/tasks/bulk"
        req = request.Request(
            bulk_url, json.dumps(payload).encode(), {"Content-Type": "application/json"}, method="POST"
        )
        try:
            with request.urlopen(req, timeout=BACKEND_TIMEOUT_SECONDS) as res:  # skipcq: BAN-B310
                if res.getcode() != 202:
                    logging.warning("Bulk update to %s failed with code %d", bulk_url, res.getcode())
                    return False
        except HTTPError as e:
            if 400 <= e.code < 500:
                logging.error("Bulk update to %s rejected with code %d, dropping %d task updates",
                              bulk_url, e.code, len(payload["tasks"]))
                return True
            logging.warning("Bulk update to %s failed with code %d", bulk_url, e.code)
            return False
        except Exception as e:  # skipcq: PYL-W0703
            logging.warning("Bulk update to %s failed: %s", bulk_url, e)
            return False
        return True

    def handle_message(self, message: dict) -> None:
        """Validates a single watcher message and stores its update"""
        if not isinstance(message, dict):
            logging.warning("Dropping malformed message: %s", message)
            return
        if not secrets.compare_digest(str(message.get("secret", "")), self.secret):
            logging.warning("Dropping message with invalid secret")
            return
        task_id = message.get("task_id")
        update_dict = message.get("update_dict")
        if task_id is None or not isinstance(update_dict, dict):
            logging.warning("Dropping malformed message: %s", message)
            return
        self.store_update(task_id=int(task_id), update_dict=update_dict)

    def run(self) -> None:
        """Receives updates until all tasks finish, the idle timeout expires or a signal arrives"""
        context = zmq.Context()
        socket_pull = context.socket(zmq.PULL)
        host = advertised_ip(self.interface)
        # listen only where the watchers are told to connect - the cluster internal network
        port = socket_pull.bind_to_random_port(f"tcp://{host}")
        write_auth_file(self.root_dir / AUTH_FILE_NAME, host=host, port=port, secret=self.secret)
        logging.info("Aggregator for simulation %d listening on %s:%d", self.sim_id, host, port)

        poller = zmq.Poller()
        poller.register(socket_pull, zmq.POLLIN)
        last_flush = last_message = time.monotonic()

        try:
            while not self.stop_event.is_set():
                events = dict(poller.poll(timeout=1000))
                if socket_pull in events:
                    try:
                        self.handle_message(json.loads(socket_pull.recv().decode()))
                    except Exception as e:  # skipcq: PYL-W0703 - one bad message must never stop the loop
                        logging.warning("Dropping undecodable message: %s", e)
                    last_message = time.monotonic()

                now = time.monotonic()
                if now - last_flush >= self.flush_interval_seconds:
                    self.flush()
                    last_flush = now
                if self.all_tasks_finished():
                    logging.info("All %d tasks reported a terminal state", self.ntasks)
                    break
                if now - last_message >= self.idle_timeout_seconds:
                    logging.warning("No updates for %.0f seconds, shutting down", self.idle_timeout_seconds)
                    break
        finally:
            try:
                self.final_flush()
            finally:
                socket_pull.close()
                context.term()
                (self.root_dir / AUTH_FILE_NAME).unlink(missing_ok=True)
                logging.info("Aggregator for simulation %d finished", self.sim_id)

    def final_flush(self) -> None:
        """Retries the last batch for a while - it carries the terminal states and the job still holds its allocation"""
        deadline = time.monotonic() + FINAL_FLUSH_DEADLINE_SECONDS
        while True:
            self.flush()
            if not self._pending or time.monotonic() >= deadline:
                break
            logging.warning("Final flush failed, %d task updates pending, retrying", len(self._pending))
            time.sleep(self.flush_interval_seconds)
        if self._pending:
            logging.error("Giving up on %d task updates", len(self._pending))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim_id", type=int, required=True)
    parser.add_argument("--update_key", type=str, required=True)
    parser.add_argument("--backend_url", type=str, required=True)
    parser.add_argument("--root_dir", type=str, required=True)
    parser.add_argument("--ntasks", type=int, required=True)
    parser.add_argument("--interface", type=str, default=os.environ.get("YAPTIDE_ZMQ_INTERFACE", DEFAULT_INTERFACE))
    parser.add_argument("--flush_interval", type=float, default=DEFAULT_FLUSH_INTERVAL_SECONDS)
    parser.add_argument("--idle_timeout", type=float, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )

    aggregator = TaskUpdateAggregator(
        sim_id=args.sim_id,
        update_key=args.update_key,
        backend_url=args.backend_url,
        root_dir=Path(args.root_dir),
        ntasks=args.ntasks,
        interface=args.interface,
        flush_interval_seconds=args.flush_interval,
        idle_timeout_seconds=args.idle_timeout,
    )

    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(stop_signal, lambda *_: aggregator.stop_event.set())

    aggregator.run()
