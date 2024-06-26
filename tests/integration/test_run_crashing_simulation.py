import copy
import json
import logging
import pytest  # skipcq: PY-W2000
from time import sleep
from flask import Flask
from celery.contrib.pytest import celery_app, celery_worker, celery_config, celery_parameters,celery_enable_logging, use_celery_app_trap, celery_includes, celery_worker_pool, celery_worker_parameters

@pytest.mark.usefixtures("live_server", "live_server_win")
def test_run_simulation_with_flask_crashing(celery_app,
                                            celery_worker,
                                            client: Flask,
                                            db_good_username: str,
                                            db_good_password: str,
                                            payload_files_dict_data: dict,
                                            modify_tmpdir,
                                            add_simulators_to_path_variable,
                                            shieldhit_binary_installed):
    """Test we can run simulations"""
    client.put("/auth/register",
               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
               content_type='application/json')
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101

    # lets make a local copy of the payload dict, so we don't modify the original one
    payload_dict_with_broken_input = copy.deepcopy(payload_files_dict_data)
    # lets set the mat.dat to empty string, so the simulation will crash
    payload_dict_with_broken_input["input_files"]["mat.dat"] = ""

    logging.info("Sending job submition request on /jobs/direct endpoint")
    resp = client.post("/jobs/direct",
                       data=json.dumps(payload_dict_with_broken_input),
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
    
    counter = 0
    wait_this_long = 30
    while True:
        if counter > wait_this_long:
            logging.error("Job did not crash in %d seconds - aborting", wait_this_long)
            assert False
        counter+=1
        logging.debug("Sending check job status request on /jobs endpoint, attempt %d", counter)
        resp = client.get("/jobs", query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        jobs_data = json.loads(resp.data.decode())

        # lets ensure that the keys contain only message, job_state and job_tasks_status
        # and that there is no results, logfiles and input files here
        assert set(jobs_data.keys()) == {"message", "job_state", "job_tasks_status"}
        assert len(jobs_data["job_tasks_status"]) == payload_dict_with_broken_input["ntasks"]
        logging.debug("Job state: %s", jobs_data['job_state'])
        for i, task_status in enumerate(jobs_data["job_tasks_status"]):
            logging.info("Task %d status %s", i, task_status)

        if jobs_data['job_state'] in ['COMPLETED', 'FAILED']:
            logging.debug("Job state is %s, breaking the loop", jobs_data['job_state'])
            assert jobs_data['job_state'] == 'FAILED'
            break
        sleep(1)

    # right now sending of logfiles is disabled
    logging.info("Fetching logfiles from /logfiles endpoint")
    resp = client.get("/logfiles", query_string={"job_id": job_id})
    assert resp.status_code == 404
