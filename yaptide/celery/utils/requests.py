import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from requests import RequestException
import yaptide.performance_tracker as tracker

_THREAD_LOCAL = threading.local()
_REQUEST_TIMEOUT = (3.0, 10.0)
_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _get_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def _post(path: str, payload: dict) -> requests.Response | None:
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return None
    try:
        return _get_session().post(url=f"{flask_url}{path}", json=payload, timeout=_REQUEST_TIMEOUT)
    except RequestException as exc:
        logging.warning("Request to %s failed: %s", path, exc)
        return None


def _send_task_update_sync(payload: dict) -> bool:
    tracker_id = tracker.start("send_task_update")
    res = _post("/tasks", payload)
    tracker.end(tracker_id)
    if res is None:
        return False
    if res.status_code != 202:
        logging.warning("Update_dict: %s", payload.get("update_dict"))
        logging.warning("Task update for %s - Failed: %s", payload.get("task_id"), res.json().get("message"))
        return False
    return True


def _fire_and_forget(func, *args, **kwargs) -> None:
    try:
        _EXECUTOR.submit(func, *args, **kwargs)
    except RuntimeError:
        func(*args, **kwargs)


def send_task_update(simulation_id: int,
                     task_id: int,
                     update_key: str,
                     update_dict: dict,
                     async_send: bool = False) -> bool:
    """Sends task status to backend which will update the database"""
    if not update_key:
        logging.warning("Update key not found, skipping update")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    logging.debug("Sending update %s to the backend /tasks", dict_to_send)
    if async_send:
        _fire_and_forget(_send_task_update_sync, dict_to_send)
        return True
    return _send_task_update_sync(dict_to_send)


def send_simulation_results(simulation_id: int, update_key: str, estimators: list) -> bool:
    """Sends simulation results to flask to save it in database"""
    if not update_key:
        logging.warning("Update key not found, skipping update")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "estimators": estimators,
    }
    logging.info("Sending results to flask")
    res = _post("/results", dict_to_send)
    if res is None:
        return False
    if res.status_code != 202:
        logging.warning("Saving results failed: %s", res.json().get("message"))
        return False
    return True


def send_simulation_logfiles(simulation_id: int, update_key: str, logfiles: dict) -> bool:
    """
    Sends simulation logfiles to Flask backend which will save it in database
    Returns True if successful, False otherwise
    """
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "logfiles": logfiles,
    }
    logging.info("Sending log files to flask")
    res = _post("/logfiles", dict_to_send)
    if res is None:
        return False
    if res.status_code != 202:
        logging.warning("Saving logfiles failed: %s", res.json()["message"])
        return False
    return True
