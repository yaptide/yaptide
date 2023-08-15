import copy
import json
import logging
import platform
import pytest  # skipcq: PY-W2000
from time import sleep
from flask import Flask


@pytest.mark.usefixtures("live_server", "live_server_win")
def test_run_simulation_with_flask(celery_app,
                                   celery_worker,
                                   client: Flask,
                                   db_good_username: str,
                                   db_good_password: str,
                                   small_simulation_payload: dict,
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

    logging.info("Sending job submition request on /jobs/direct endpoint")
    resp = client.post("/jobs/direct",
                       data=json.dumps(small_simulation_payload),
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

    resp = client.get("/inputs", query_string={"job_id": job_id})
    data = json.loads(resp.data.decode())
    assert {"message", "input"} == set(data.keys())
    assert {"input_type", "input_files", "input_json", "number_of_all_primaries"} == set(data["input"].keys())
    required_converted_files = {"beam.dat", "detect.dat", "geo.dat", "info.json", "mat.dat"}
    assert required_converted_files == required_converted_files.intersection(set(data["input"]["input_files"].keys()))

    while True:
        logging.info("Sending check job status request on /jobs endpoint")
        resp = client.get("/jobs",
                          query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        data = json.loads(resp.data.decode())

        # lets ensure that the keys contain only message, job_state and job_tasks_status
        # and that there is no results, logfiles and input files here
        assert set(data.keys()) == {"message", "job_state", "job_tasks_status"}
        assert len(data["job_tasks_status"]) == small_simulation_payload["ntasks"]
        if data['job_state'] in ['COMPLETED', 'FAILED']:
            assert data['job_state'] == 'COMPLETED'
            break
        sleep(1)

    logging.info("Fetching results from /results endpoint")
    resp = client.get("/results", query_string={"job_id": job_id})
    data: dict = json.loads(resp.data.decode())
    print(data)

    assert resp.status_code == 200  # skipcq: BAN-B101
    assert {"message", "estimators"} == set(data.keys())
