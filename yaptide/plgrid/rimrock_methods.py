from enum import Enum
import requests

from yaptide.plgrid.string_templates import SHIELDHIT_BASH

HTTP_RIMROCK_JOBS = 'https://rimrock.plgrid.pl/api/jobs'
HOSTNAME = 'ares'


class JobStatus(Enum):
    """Job status types"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


def submit_job(json_data: dict) -> tuple[dict, int]:
    """Function submiting jobs to rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    data = {
        "host": f'{HOSTNAME}.cyfronet.pl',
        "script": SHIELDHIT_BASH.format(
            beam=json_data["beam.dat"],
            detect=json_data["detect.dat"],
            geo=json_data["geo.dat"],
            mat=json_data["mat.dat"]
        ),
        "tag": "yaptide_job"
    }

    res: requests.Response = session.post(HTTP_RIMROCK_JOBS, json=data, headers=headers)
    res_json = res.json()
    return res_json, res.status_code


def get_job(json_data: dict) -> tuple[dict, int]:
    """Function getting jobs' info from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    if "job_id" in json_data:
        res: requests.Response = session.get(f'{HTTP_RIMROCK_JOBS}/{json_data["job_id"]}', headers=headers)
        res_json = res.json()
        if res.status_code == 200:
            return res_json, res.status_code
    else:
        res: requests.Response = session.get(HTTP_RIMROCK_JOBS, params={"tag": "yaptide_job"}, headers=headers)
        res_json = res.json()
        if res.status_code == 200:
            return {
                "job_list": res_json
            }, res.status_code
    return res_json, res.status_code


def delete_job(json_data: dict) -> tuple[dict, int]:
    """Function deleting jobs from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    res: requests.Response = session.delete(f'{HTTP_RIMROCK_JOBS}/{json_data["job_id"]}', headers=headers)
    if res.status_code == 204:
        return {
            "message": "Job deleted"
        }, res.status_code
    res_json = res.json()
    return res_json, res.status_code
