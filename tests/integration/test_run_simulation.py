from datetime import datetime
import json
import logging
import pytest  # skipcq: PY-W2000
from time import sleep
from flask import Flask


@pytest.mark.usefixtures("live_server", "live_server_win")
def test_run_simulation_with_flask(celery_app, celery_worker, client: Flask, db_good_username: str,
                                   db_good_password: str, small_simulation_payload: dict,
                                   add_simulators_to_path_variable, shieldhit_binary_installed):
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
    resp = client.post("/jobs/direct", data=json.dumps(small_simulation_payload), content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    jobs_direct_data = json.loads(resp.data.decode())
    assert {"message", "job_id"} == set(jobs_direct_data.keys())
    job_id = jobs_direct_data["job_id"]

    logging.info("Sending request checking if input data is stored in the database")
    # send back higher level data: input_file, project_data, as in ex1.json
    # for input we need to add following fields static fields (on same level as input_type):
    #   - number of particles (backend needs to calculate that if user requested simulation with files)
    #   - calculation engine: direct (celery) or batch (slurm)
    #   - cluster_name: name of the cluster where the job is running (if slurm is used)
    #   - simulation_type: shieldhit / Fluka / TOPAS
    # some of the stuff above is in the user/simulation endpoint

    resp = client.get("/inputs", query_string={"job_id": job_id})
    inputs_data = json.loads(resp.data.decode())
    assert {"message", "input"} == set(inputs_data.keys())
    assert {"input_type", "input_files", "input_json", "number_of_all_primaries"} == set(inputs_data["input"].keys())
    required_converted_files = {"beam.dat", "detect.dat", "geo.dat", "info.json", "mat.dat"}
    assert required_converted_files == required_converted_files.intersection(
        set(inputs_data["input"]["input_files"].keys()))
    requested_primaries = small_simulation_payload["input_json"]["beam"]["numberOfParticles"]
    requested_primaries /= small_simulation_payload["ntasks"]

    max_number_of_attempts = 20
    for i in range(max_number_of_attempts):
        logging.info("Sending check job status request on /jobs endpoint, attempt %d", i)
        resp = client.get("/jobs", query_string={"job_id": job_id})
        assert resp.status_code == 200  # skipcq: BAN-B101
        jobs_data = json.loads(resp.data.decode())

        # lets ensure that the keys contain only message, job_state and job_tasks_status
        # and that there is no results, logfiles and input files here
        assert set(jobs_data.keys()) == {"message", "job_state", "job_tasks_status"}
        assert len(jobs_data["job_tasks_status"]) == small_simulation_payload["ntasks"]
        logging.debug("Job state: %s", jobs_data["job_state"])
        if jobs_data["job_state"] == 'RUNNING':
            # when job is is running, at least one task should be running
            # its interesting that it may happen that a job is RUNNING and still all tasks may be COMPLETED
            assert any(task["task_state"] in {"RUNNING", "PENDING", "COMPLETED"}
                       for task in jobs_data["job_tasks_status"])

            # check if during execution we have non-empty start_time  and empty end_time
            resp = client.get("/user/simulations")
            assert resp.status_code == 200  # skipcq: BAN-B101
            simulations_data = json.loads(resp.data.decode())
            assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(simulations_data.keys())
            assert len(simulations_data["simulations"]) == 1
            start_time = simulations_data["simulations"][0]["start_time"]
            logging.info("start_time: %s", start_time)
            assert start_time is not None

        logging.info("Checking if number of simulated primaries is correct")
        if jobs_data["job_state"] == 'COMPLETED':
            for task in jobs_data["job_tasks_status"]:
                assert task["task_state"] == "COMPLETED"
                logging.info("Expecting requested_primaries: %s", requested_primaries)
                logging.info("Expecting simulated_primaries: %s", requested_primaries)
                logging.info("Got requested_primaries: %s", task["requested_primaries"])
                logging.info("Got simulated_primaries: %s", task["simulated_primaries"])
                assert task[
                    "requested_primaries"] == requested_primaries, f"Requested primaries should be equal to {requested_primaries}"
                assert task[
                    "simulated_primaries"] == requested_primaries, f"Simulated primaries should be equal to {requested_primaries}"
        if jobs_data['job_state'] in ['COMPLETED', 'FAILED']:
            assert jobs_data['job_state'] == 'COMPLETED'
            logging.info("Job completed, exiting loop")
            break
        sleep(0.5)
    assert i < max_number_of_attempts - 1, "Job did not finish in time"

    logging.info("Fetching results from /results endpoint")
    resp = client.get("/results", query_string={"job_id": job_id})
    results_data: dict = json.loads(resp.data.decode())

    assert resp.status_code == 200  # skipcq: BAN-B101
    assert {"message", "estimators"} == set(results_data.keys())

    resp = client.get("/user/simulations")
    assert resp.status_code == 200  # skipcq: BAN-B101
    simulations_data = json.loads(resp.data.decode())
    # check if we get expected keys in the response
    assert {'message', 'simulations_count', 'simulations', 'page_count'} == set(simulations_data.keys())
    # check if we get expected number of simulations in the response in the first page
    assert len(simulations_data["simulations"]) == 1, "We should get exactly one simulation"
    start_time = simulations_data["simulations"][0]["start_time"]
    logging.info("start_time: %s", start_time)
    assert start_time is not None, "simulation start_time should not be None"
    end_time = simulations_data["simulations"][0]["end_time"]
    logging.info("end_time: %s", end_time)
    assert end_time is not None, "simulation end_time should not be None"
    datetime_starttime = datetime.strptime(start_time, "%a, %d %b %Y %H:%M:%S %Z")
    datetime_endtime = datetime.strptime(end_time, "%a, %d %b %Y %H:%M:%S %Z")
    assert datetime_endtime > datetime_starttime, "simulation end_time should be after start_time"
