import copy
import json
import logging
import platform
import pytest
from time import sleep
from flask import Flask

from yaptide.persistence.database import db


# @pytest.mark.skip(reason="no way of currently testing this")
def test_list_simulations(celery_app, 
                                   celery_worker, 
                                   client_fixture: Flask, 
                                   db_good_username: str, 
                                   db_good_password: str, 
                                   payload_editor_dict_data: dict,
                                   add_directory_to_path,
                                   shieldhit_demo_binary):
    """Test we can run simulations"""
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
    payload_dict["ntasks"] = 1
    payload_dict["input_json"]["beam"]["numberOfParticles"] = 12

    if platform.system() == "Windows":
        payload_dict["input_json"]["detectManager"]["filters"] = []
        payload_dict["input_json"]["detectManager"]["detectGeometries"] = [payload_dict["input_json"]["detectManager"]["detectGeometries"][0]]
        payload_dict["input_json"]["scoringManager"]["scoringOutputs"] = [payload_dict["input_json"]["scoringManager"]["scoringOutputs"][0]]
        for output in payload_dict["input_json"]["scoringManager"]["scoringOutputs"]:
            for quantity in output["quantities"]["active"]:
                if "filter" in quantity:
                    del quantity["filter"]

    logging.info("Sending job submition request on /jobs/direct endpoint")
    number_of_simulations = 8
    for _ in range(number_of_simulations):
        resp = client_fixture.post("/jobs/direct",
                                data=json.dumps(payload_dict),
                                content_type='application/json')

        assert resp.status_code == 202  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())
        assert {"message", "job_id"} == set(data.keys())

    logging.info("Check basic list of simulations")

    resp = client_fixture.get("/user/simulations")
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert {"message", "simulations", "page_count", "simulations_count"} == set(data.keys())
    assert data["simulations_count"] == number_of_simulations

    logging.info("Check basic list of simulations with pagination")

    # for page_size in range(2, 5):
    page_size=3
    resp = client_fixture.get("/user/simulations",
                              query_string={"page_size": page_size, "page_idx": 1, "order_by": "start_time", "order_type": "desc"})
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert {"message", "simulations", "page_count", "simulations_count"} == set(data.keys())
    assert data["simulations_count"] == number_of_simulations
    assert data["page_count"] == number_of_simulations // page_size + 1 if number_of_simulations % page_size else 0
    assert len(data["simulations"]) == page_size
















