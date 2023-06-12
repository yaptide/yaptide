import copy
import json
import logging
import platform
from time import sleep
import pytest  # skipcq: PY-W2000
from flask import Flask

@pytest.mark.usefixtures("live_server", "live_server_win")
def test_list_simulations(celery_app,
                          celery_worker,
                          client: Flask,
                          db_good_username: str,
                          db_good_password: str,
                          payload_editor_dict_data: dict,
                          add_directory_to_path,
                          shieldhit_demo_binary):
    """Test we can run simulations"""
    client.put("/auth/register",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')
    resp = client.post("/auth/login",
                               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101

    payload_dict = copy.deepcopy(payload_editor_dict_data)

    # limit the particle numbers to get faster results
    payload_dict["ntasks"] = 2
    payload_dict["input_json"]["beam"]["numberOfParticles"] = 12

    if platform.system() == "Windows":
        payload_dict["input_json"]["detectManager"]["filters"] = []
        payload_dict["input_json"]["detectManager"]["detectGeometries"] = [payload_dict["input_json"]["detectManager"]["detectGeometries"][0]]
        payload_dict["input_json"]["scoringManager"]["scoringOutputs"] = [payload_dict["input_json"]["scoringManager"]["scoringOutputs"][0]]
        for output in payload_dict["input_json"]["scoringManager"]["scoringOutputs"]:
            for quantity in output["quantities"]["active"]:
                if "filter" in quantity:
                    del quantity["filter"]

    logging.info("Sending multiple job submition requests on /jobs/direct endpoint to test pagination")
    number_of_simulations = 5
    for _ in range(number_of_simulations):
        resp = client.post("/jobs/direct",
                                data=json.dumps(payload_dict),
                                content_type='application/json')

        assert resp.status_code == 202  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())
        assert {"message", "job_id"} == set(data.keys())
        sleep(1)

    logging.info("Check basic list of simulations")

    resp = client.get("/user/simulations")
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    for item in data["simulations"]:
        logging.info(item)
    assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(data.keys())
    assert data["simulations_count"] == number_of_simulations
    start_time_of_newest_simulation = data["simulations"][0]["start_time"]
    start_time_of_second_newest_simulation = data["simulations"][1]["start_time"]

    logging.info("Check basic list of simulations with pagination")

    page_size=3
    resp = client.get("/user/simulations",
                              query_string={"page_size": page_size, "page_idx": 0, "order_by": "start_time", "order_type": "desc"})
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    for item in data["simulations"]:
        logging.info(item.keys())
    assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(data.keys())
    assert data["simulations_count"] == number_of_simulations
    assert data["page_count"] == number_of_simulations // page_size + 1 if number_of_simulations % page_size else 0
    assert len(data["simulations"]) == page_size
    assert data["simulations"][0]["start_time"] == start_time_of_newest_simulation
    assert data["simulations"][1]["start_time"] == start_time_of_second_newest_simulation
