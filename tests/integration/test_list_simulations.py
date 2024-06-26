from datetime import datetime
import json
import logging
from time import sleep
import pytest  # skipcq: PY-W2000
from flask import Flask

from yaptide.routes.user_routes import DEFAULT_PAGE_SIZE

# skipcq: PY-W2000
from celery.contrib.pytest import celery_app, celery_worker, celery_config, celery_enable_logging, celery_parameters, use_celery_app_trap, celery_includes, celery_worker_pool


@pytest.mark.usefixtures("live_server", "live_server_win")
def test_list_simulations(celery_app, celery_worker, client: Flask, db_good_username: str, db_good_password: str,
                          small_simulation_payload: dict, add_simulators_to_path_variable, shieldhit_binary_installed):
    """Test we can run simulations"""
    client.put("/auth/register",
               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
               content_type='application/json')
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101

    logging.info("Sending multiple job submition requests on /jobs/direct endpoint to test pagination")
    # by default we have 6 simulations per page, therefore we need to send 7 to test pagination
    number_of_simulations = 7
    for _ in range(number_of_simulations):
        resp = client.post("/jobs/direct", data=json.dumps(small_simulation_payload), content_type='application/json')

        assert resp.status_code == 202  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())
        assert {"message", "job_id"} == set(data.keys())
        sleep(1)

    logging.info("Check basic list of simulations")

    resp = client.get("/user/simulations")
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    logging.info("all simulations")
    for item in data["simulations"]:
        logging.info(item["start_time"])
    # check if we get expected keys in the response
    assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(data.keys())
    # check if we get expected total number of simulations in the response
    assert data["simulations_count"] == number_of_simulations
    # check if we get expected number of pages in the response
    assert data["page_count"] == 2
    # check if we get expected number of simulations in the response in the first page
    # note that we have DEFAULT_PAGE_SIZE (6) simulations per page by default
    assert len(data["simulations"]) == DEFAULT_PAGE_SIZE
    start_time_of_newest_simulation = data["simulations"][0]["start_time"]
    start_time_of_second_newest_simulation = data["simulations"][1]["start_time"]
    # convert to datetime object to compare
    datetime_newest = datetime.strptime(start_time_of_newest_simulation, "%a, %d %b %Y %H:%M:%S %Z")
    datetime_second_newest = datetime.strptime(start_time_of_second_newest_simulation, "%a, %d %b %Y %H:%M:%S %Z")
    # we requested simulation with default descending order by start_time
    # check if newest simulation is newer than second newest simulation
    assert datetime_newest > datetime_second_newest

    logging.info("Check basic list of simulations with pagination")

    # check first page with 3 items out of 7
    page_size = 3
    resp = client.get("/user/simulations",
                      query_string={
                          "page_size": page_size,
                          "page_idx": 1,
                          "order_by": "start_time",
                          "order_type": "descend"
                      })
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    logging.info("descending order, page 1")
    for item in data["simulations"]:
        logging.info(item["start_time"])
    assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(data.keys())
    assert data["simulations_count"] == number_of_simulations
    assert data["page_count"] == 3
    assert len(data["simulations"]) == page_size
    assert data["simulations"][0]["start_time"] == start_time_of_newest_simulation
    assert data["simulations"][1]["start_time"] == start_time_of_second_newest_simulation

    # check second page with 1 item out of 7, not different ordering
    resp = client.get("/user/simulations",
                      query_string={
                          "page_size": page_size,
                          "page_idx": 3,
                          "order_by": "start_time",
                          "order_type": "ascend"
                      })
    assert resp.status_code == 200  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    logging.info("ascending order, page 3")
    for item in data["simulations"]:
        logging.info(item["start_time"])
    assert data["page_count"] == 3
    assert len(data["simulations"]) == 1
    assert data["simulations"][0]["start_time"] == start_time_of_newest_simulation
