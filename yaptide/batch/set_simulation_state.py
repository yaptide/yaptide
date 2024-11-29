from enum import Enum
import argparse
import json
import logging
import signal
import ssl
from urllib import request


def send_request(simulation_id: int, backend_url: str, simulation_state: str):
    """Sends simulation state to backend"""
    dict_to_send = {"sim_id": simulation_id, "job_state": simulation_state.value}
    jobs_url = f"{backend_url}/jobs"
    context = ssl.SSLContext()

    req = request.Request(jobs_url,
                          json.dumps(dict_to_send).encode(), {'Content-Type': 'application/json'},
                          method='POST')
    try:
        with request.urlopen(req, context=context) as res:  # skipcq: BAN-B310
            if res.getcode() != 202:
                logging.warning("Sending update to %s failed", jobs_url)
    except Exception as e:  # skipcq: PYL-W0703
        print(e)


class EntityState(Enum):
    """Job state types"""
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    MERGING_QUEUED = "MERGING_QUEUED"
    MERGING_RUNNING = "MERGING_RUNNING"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


if __name__ == "__main__":
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler()])

    parser = argparse.ArgumentParser()
    parser.add_argument("--sim_id", type=int)
    parser.add_argument("--backend_url", type=str)
    parser.add_argument("--entityState", type=str)
    args = parser.parse_args()

    state = EntityState[args.entityState]
    send_request(simulation_id=args.sim_id, backend_url=args.backend_url, simulation_state=state)
