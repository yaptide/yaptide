import logging
from time import sleep
import json
from flask import Flask

from yaptide.persistence.database import db


def test_run_simulation_with_flask(celery_app, celery_worker, client_fixture: Flask, db_good_username: str, db_good_password: str, payload_editor_dict_data: dict):
    """Test if user can log in"""
    client_fixture.put("/auth/register",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')
    resp = client_fixture.post("/auth/login",
                               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101

    resp = client_fixture.post("/jobs/direct",
                               data=json.dumps(payload_editor_dict_data),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert "job_id" in data
    job_id = data["job_id"]

    while True:
        resp = client_fixture.get("/jobs/direct",
                                  query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        logging.info(resp.data)
        data = json.loads(resp.data.decode())
        assert "job_state" in data
        assert "job_tasks_status" in data
        if data['job_state'] == 'COMPLETED':
            break
        sleep(1)
