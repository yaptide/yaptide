import logging
import os


import requests


def send_task_update(simulation_id: int, task_id: str, update_key: str, update_dict: dict) -> bool:
    """Sends task update to flask to update database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "task_id": task_id,
        "update_key": update_key,
        "update_dict": update_dict
    }
    res: requests.Response = requests.Session().post(url=f"{flask_url}/tasks/update", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Task update for %s - Failed: %s", task_id, res.json().get("message"))
        return False
    return True


def send_simulation_results(simulation_id: int, update_key: str, estimators: dict) -> bool:
    """Sends results of simulation to flask to save it in database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "estimators": estimators["estimators"],
    }
    logging.info("Sending results to flask via %s", flask_url)
    res: requests.Response = requests.Session().post(url=f"{flask_url}/results", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Saving results failed: %s", res.json().get("message"))
        return False
    return True


def send_simulation_logfiles(simulation_id: int, update_key: str, logfiles: dict) -> bool:
    """Sends results of simulation to flask to save it in database"""
    flask_url = os.environ.get("BACKEND_INTERNAL_URL")
    if not flask_url:
        logging.warning("Flask URL not found via BACKEND_INTERNAL_URL")
        return False
    dict_to_send = {
        "simulation_id": simulation_id,
        "update_key": update_key,
        "logfiles": logfiles,
    }
    logging.info("Sending log files to flask via %s", flask_url)
    res: requests.Response = requests.Session().post(url=f"{flask_url}/logfiles", json=dict_to_send)
    if res.status_code != 202:
        logging.warning("Saving logfiles failed: %s", res.json()["message"])
        return False
    return True