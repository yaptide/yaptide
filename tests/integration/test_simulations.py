import copy
import json
import logging
import platform
from time import sleep
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

    payload_dict = copy.deepcopy(payload_editor_dict_data)

    # limit the particle numbers to get faster results
    payload_dict["sim_data"]["beam"]["numberOfParticles"] = 12

    if platform.system() == "Windows":
        payload_dict["sim_data"]["detectManager"]["filters"] = []
        payload_dict["sim_data"]["detectManager"]["detectGeometries"] = [payload_dict["sim_data"]["detectManager"]["detectGeometries"][0]]
        payload_dict["sim_data"]["scoringManager"]["scoringOutputs"] = [payload_dict["sim_data"]["scoringManager"]["scoringOutputs"][0]]
        for output in payload_dict["sim_data"]["scoringManager"]["scoringOutputs"]:
            for quantity in output["quantities"]["active"]:
                if "filter" in quantity:
                    del quantity["filter"]

    resp = client_fixture.post("/jobs/direct",
                               data=json.dumps(payload_dict),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert "job_id" in data
    job_id = data["job_id"]

    while True:
        resp = client_fixture.get("/jobs/direct",
                                  query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())
        logging.info(data["message"])
        assert "job_state" in data
        assert "job_tasks_status" in data
        assert len(data["job_tasks_status"]) == payload_dict["ntasks"]
        if data['job_state'] == 'COMPLETED':
            break
        sleep(1)

    resp = client_fixture.get("/results/direct",
                              query_string={"job_id": job_id})
    data: dict = json.loads(resp.data.decode())
    logging.info(data["message"])
    assert data == "Job results"
    assert resp.status_code == 200  # skipcq: BAN-B101
    assert "result" in data
