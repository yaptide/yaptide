import requests
import base64
import os
from pathlib import Path

http_rimrock_jobs = 'https://rimrock.pre.plgrid.pl/api/jobs'
http_plgdata = 'https://data.plgrid.pl'
hostname = 'ares'
bash_path = Path(os.path.dirname(os.path.realpath(__file__)), 'sh_run.sh')


def submit_job(json_data: dict) -> dict:
    """Function submiting jobs to rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data["grid_proxy"]
    }
    data = {
        "host": f'{hostname}.cyfronet.pl'
    }
    if json_data.get("bash_file"):
        data["script"] = json_data["bash_file"]
    else:
        with open(bash_path) as bash_file:
            data["script"] = bash_file.read()

    res: requests.Response = session.post(http_rimrock_jobs, json=data, headers=headers)
    res_json = res.json()
    if res.status_code == 201:
        return {
            "status": res.status_code,
            "job_id": res_json["job_id"],
            "job_status": res_json["status"]
        }
    return {
        "status": res.status_code,
        "error_message": res_json["error_message"],
        "error_output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }


def get_job(json_data: dict) -> dict:
    """Function getting jobs' info from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data["grid_proxy"]
    }
    res: requests.Response = session.get(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    res_json = res.json()
    if res.status_code == 200:
        return {
            "status": res.status_code,
            "job_id": res_json["job_id"],
            "job_status": res_json["status"]
        }
    return {
        "status": res.status_code,
        "error_message": res_json["error_message"],
        "error_output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }


def delete_job(json_data: dict) -> dict:
    """Function deleting jobs from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data["grid_proxy"]
    }
    res: requests.Response = session.delete(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    if res.status_code == 204:
        return {
            "status": res.status_code,
            "message": "Task deleted"
        }
    res_json = res.json()
    return {
        "status": res.status_code,
        "error_message": res_json["error_message"],
        "error_output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }
