import logging
import os
import time
from typing import Optional

import requests

# about a minute - long enough to outlast a restart of the backend
FINAL_POST_ATTEMPTS = 6
FINAL_POST_RETRY_SECONDS = 10


def _post(path: str, payload: dict, attempts: int = 1, timeout=30) -> Optional[bool]:
    """Posts to the backend; never raises

    True when accepted, False when refused for good (worth no retry), None when the backend could not be reached.
    """
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    for attempt in range(attempts):
        if attempt:
            time.sleep(FINAL_POST_RETRY_SECONDS)
        try:
            res = requests.Session().post(url=f"{flask_url}{path}", json=payload, timeout=timeout)
        except requests.exceptions.InvalidJSONError as e:
            logging.error("POST %s has a payload that is not valid JSON: %s", path, e)
            return False
        except requests.RequestException as e:
            logging.warning("POST %s failed (attempt %d/%d): %s", path, attempt + 1, attempts, e)
            continue
        if res.status_code == 202:
            return True
        logging.warning("POST %s rejected with %d: %s", path, res.status_code, res.text[:300])
        # the backend answered - only its own errors are worth another try (501 means "no such simulation")
        if res.status_code < 500 or res.status_code == 501:
            return False
    return None


def send_task_updates(simulation_id: int, update_key: str, updates: dict[int, dict]) -> Optional[bool]:
    """Sends the collected updates of many tasks in one request, task id -> update_dict; None: backend unreachable"""
    tasks = [{"task_id": task_id, "update_dict": update_dict} for task_id, update_dict in updates.items()]
    return _post("/tasks/bulk", {"simulation_id": simulation_id, "update_key": update_key, "tasks": tasks})


def send_job_state(simulation_id: int, update_key: str, update_dict: dict, attempts: int = 1) -> bool:
    """Sends the state of the whole simulation, e.g. MERGING_RUNNING or FAILED"""
    return bool(_post("/jobs", {"sim_id": simulation_id, "update_key": update_key, **update_dict}, attempts=attempts))


def send_simulation_results(simulation_id: int, update_key: str, estimators: list) -> bool:
    """Sends simulation results to flask to save it in database, retrying so a backend restart does not lose them"""
    if not update_key:
        logging.warning("Update key not found, skipping update")
        return False
    payload = {"simulation_id": simulation_id, "update_key": update_key, "estimators": estimators}
    # the read timeout is longer than gunicorn's, so it ends only after the backend gave up - no attempts overlap
    return bool(_post("/results", payload, attempts=FINAL_POST_ATTEMPTS, timeout=(10, 600)))


def send_simulation_logfiles(simulation_id: int, update_key: str, logfiles: dict) -> bool:
    """Sends simulation logfiles to Flask backend which will save it in database"""
    payload = {"simulation_id": simulation_id, "update_key": update_key, "logfiles": logfiles}
    return bool(_post("/logfiles", payload, attempts=FINAL_POST_ATTEMPTS))
