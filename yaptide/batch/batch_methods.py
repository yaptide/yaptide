import json as json_lib
import os

import time
from datetime import datetime

from pathlib import Path

from enum import Enum

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


class JobStatus(Enum):
    """Job status types - move it to more utils like place in future"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


def submit_job(json_data: dict) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of submit_job"""
    return {
        "message": "Dummy submit",
        "job_id": int(time.time()*10000)  # dummy job_id based on current time
    }, 202


def get_job(json_data: dict) -> tuple[dict, int]:
    """Dummy version of get_job"""
    now = datetime.utcnow()
    time_diff = now - json_data["start_time_for_dummy"]
    print(time_diff)
    print(json_data)
    if time_diff.seconds < 30 and json_data["end_time_for_dummy"] is None:
        return {
            "job_tasks_status": [
                {
                    "state": JobStatus.RUNNING.value,
                    "info": {
                        'simulated_primaries': 1000,
                        'primaries_to_simulate': 2000,
                        'estimated': {
                            'hours': 0,
                            'minutes': 0,
                            'seconds': 15,
                        }
                    }
                }
            ]
        }, 200

    with open(Path(ROOT_DIR, "dummy_output.json")) as json_file:
        result = json_lib.load(json_file)
    return {
        "result": result,
        "end_time": now,
        "cores": 1
    }, 200


def delete_job(json_data: dict) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of delete_job"""
    return {"message": "Not implemented yet"}, 404


def fetch_bdo_files(json_data: dict) -> tuple[dict, int]:  # skipcq: PYL-W0613
    """Dummy version of fetch_bdo_files"""
    return {"message": "Not implemented yet"}, 404
