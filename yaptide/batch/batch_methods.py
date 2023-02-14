import json as json_lib
import os

import time
from datetime import datetime

from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))

def submit_job(json_data: dict) -> tuple[dict, int]:
    """Dummy version of submit_job"""
    return {
        "message": "Dummy submit",
        "job_id": int(time.time()*10000) # dummy job_id based on current time
    }, 202

def get_job(json_data: dict) -> tuple[dict, int]:
    """Dummy version of get_job"""
    with open(Path(ROOT_DIR, "dummy_output.json")) as json_file:
        result = json_lib.load(json_file)
    return {
        "result": result,
        'end_time': datetime.utcnow(),
        'cores': 1 # dummy value
    }, 200

def delete_job(json_data: dict) -> tuple[dict, int]:
    """Dummy version of delete_job"""
    return {"message": "Not implemented yet"}, 404

def fetch_bdo_files(json_data: dict) -> tuple[dict, int]:
    """Dummy version of fetch_bdo_files"""
    return {"message": "Not implemented yet"}, 404
