import requests
import os
from pathlib import Path

from plgrid.rimrock_bash import shieldhit_bash

http_rimrock_jobs = 'https://rimrock.pre.plgrid.pl/api/jobs'
hostname = 'ares'


def submit_job(json_data: dict) -> tuple[dict, int]:
    """Function submiting jobs to rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    data = {
        "host": f'{hostname}.cyfronet.pl',
        "script": shieldhit_bash.format(
            beam=json_data["beam.dat"],
            detect=json_data["detect.dat"],
            geo=json_data["geo.dat"],
            mat=json_data["mat.dat"]
        )
    }
    print(data)

    res: requests.Response = session.post(http_rimrock_jobs, json=data, headers=headers)
    res_json = res.json()
    if res.status_code == 201:
        return {
            "job_id": res_json["job_id"],
            "job_status": res_json["status"],
            "message": "Job submitted"
        }, res.status_code
    return {
        "message": res_json["error_message"],
        "output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }, res.status_code


def get_job(json_data: dict) -> tuple[dict, int]:
    """Function getting jobs' info from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    res: requests.Response = session.get(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    res_json = res.json()
    if res.status_code == 200:
        return {
            "job_id": res_json["job_id"],
            "job_status": res_json["status"],
            "message": "Job status"
        }, res.status_code
    return {
        "message": res_json["error_message"],
        "output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }, res.status_code


def delete_job(json_data: dict) -> tuple[dict, int]:
    """Function deleting jobs from rimrock"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    res: requests.Response = session.delete(f'{http_rimrock_jobs}/{json_data["job_id"]}', headers=headers)
    if res.status_code == 204:
        return {
            "message": "Job deleted"
        }, res.status_code
    res_json = res.json()
    return {
        "message": res_json["error_message"],
        "output": res_json["error_output"],
        "exit_code": res_json["exit_code"]
    }, res.status_code
