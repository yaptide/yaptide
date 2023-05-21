import copy
import json
import logging
import platform
import pytest  # skipcq: PY-W2000
from time import sleep
from flask import Flask


def test_run_simulation_with_flask(celery_app, 
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
    resp = client_fixture.post("/jobs/direct",
                               data=json.dumps(payload_dict),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    data = json.loads(resp.data.decode())
    assert {"message", "job_id"} == set(data.keys())
    job_id = data["job_id"]

    logging.info("Sending request checking if input data is stored in the database")
    # send back higher level data: input_file, project_data, as in ex1.json
    # for input we need to add following fields static fields (on same level as input_type):
    #   - number of particles (backend needs to calculate that if user requested simulation with files)
    #   - calculation engine: direct (celery) or batch (slurm)
    #   - cluster_name: name of the cluster where the job is running (if slurm is used)
    #   - simulation_type: shieldhit / Fluka / TOPAS
    # some of the stuff above is in the user/simulation endpoint

    resp = client_fixture.get("/inputs", 
                              query_string={"job_id": job_id})
    data = json.loads(resp.data.decode())
    assert {"message", "input"} == set(data.keys())
    assert {"input_type", "input_files", "input_json", "number_of_all_primaries"} == set(data["input"].keys())
    required_converted_files = {"beam.dat", "detect.dat", "geo.dat", "info.json", "mat.dat"}
    assert required_converted_files == required_converted_files.intersection(set(data["input"]["input_files"].keys()))
    
    while True:
        logging.info("Sending check job status request on /jobs/direct endpoint")
        resp = client_fixture.get("/jobs/direct",
                                  query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())

        # lets ensure that the keys contain only message, job_state and job_tasks_status
        # and that there is no results and input files here
        assert set(data.keys()) == {"message", "job_state", "job_tasks_status"}
        assert len(data["job_tasks_status"]) == payload_dict["ntasks"]
        if data['job_state'] in ['COMPLETED', 'FAILED']:
            break
        sleep(1)

    logging.info("Fetching results from /results endpoint")
    resp = client_fixture.get("/results",
                              query_string={"job_id": job_id})
    data: dict = json.loads(resp.data.decode())

    assert resp.status_code == 404  # skipcq: BAN-B101
    if resp.status_code == 404:
        assert {"message"} == set(data.keys())
    else:
        assert {"message", "estimators"} == set(data.keys())
