import copy
import json
import logging
import pytest  # skipcq: PY-W2000
from time import sleep
from flask import Flask


@pytest.mark.usefixtures("live_server", "live_server_win")
def test_run_simulation_with_flask_crashing(celery_app,
                                            celery_worker,
                                            client: Flask,
                                            db_good_username: str,
                                            db_good_password: str,
                                            payload_files_dict_data: dict,
                                            add_directory_to_path,
                                            modify_tmpdir,
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

    payload_dict = copy.deepcopy(payload_files_dict_data)
    payload_dict["input_files"]["mat.dat"] = ""

    logging.info("Sending job submition request on /jobs/direct endpoint")
    resp = client.post("/jobs/direct",
                       data=json.dumps(payload_dict),
                       content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert {"message", "job_id"} == set(data.keys())
    job_id = data["job_id"]

    logging.info("Sending request checking if input data is stored in the database")

    resp = client.get("/inputs", query_string={"job_id": job_id})
    data = json.loads(resp.data.decode())
    assert {"message", "input"} == set(data.keys())
    assert {"input_type", "input_files", "number_of_all_primaries"} == set(data["input"].keys())
    required_converted_files = {"beam.dat", "detect.dat", "geo.dat", "info.json", "mat.dat"}
    assert required_converted_files == required_converted_files.intersection(set(data["input"]["input_files"].keys()))
    
    while True:
        logging.info("Sending check job status request on /jobs/direct endpoint")
        resp = client.get("/jobs/direct", query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())

        # lets ensure that the keys contain only message, job_state and job_tasks_status
        # and that there is no results, logfiles and input files here
        assert set(data.keys()) == {"message", "job_state", "job_tasks_status"}
        assert len(data["job_tasks_status"]) == payload_dict["ntasks"]
        logging.info("Data from /jobs/direct endpoint: {%s}", data)
        logging.info("Job state: {%s}", data['job_state'])
        if data['job_state'] in ['COMPLETED', 'FAILED']:
            assert data['job_state'] == 'FAILED'
            break
        sleep(1)

    logging.info("Fetching logfiles from /logfiles endpoint")
    resp = client.get("/logfiles", query_string={"job_id": job_id})
    data: dict = json.loads(resp.data.decode())
    print(data)

    assert resp.status_code == 200  # skipcq: BAN-B101
    assert {"message", "logfiles"} == set(data.keys())
