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
    if json_data.get("bash_file"):
        data = {
            "host": f'{hostname}.cyfronet.pl',
            "script": json_data["bash_file"]
        }
    else:
        with open(bash_path) as bash_file:
            data = {
                "host": f'{hostname}.cyfronet.pl',
                "script": bash_file.read()
            }

    res: requests.Response = session.post(http_rimrock_jobs, json=data, headers=headers)
    return {
        "status": res.status_code,
        "json": res.json()
    }


def get_job(json_data: dict) -> dict:
    """Function getting jobs' info from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data["grid_proxy"]
    }
    res: requests.Response = session.get(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    return {
        "status": res.status_code,
        "json": res.json()
    }


def delete_job(json_data: dict) -> dict:
    """Function deleting jobs from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data["grid_proxy"]
    }
    res: requests.Response = session.delete(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    return {
        "status": res.status_code,
        "json": res.json()
    }
