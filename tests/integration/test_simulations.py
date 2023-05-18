import copy
import json
import logging
import platform
import pytest
from time import sleep
from flask import Flask

from yaptide.persistence.database import db


# @pytest.mark.skip(reason="no way of currently testing this")
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
    # we expect another change on UI
    # we remove sim_data, we add input_type, input_files and input_editor
    # we add input_file
    # send back higher level data: input_file, project_data, as in ex1.json
    # for input we need to add following fields static fields (on same level as input_type):
    #   - number of particles (backend needs to calculate that if user requested simulation with files)
    #   - calculation engine: direct (celery) or batch (slurm)
    #   - cluster_name: name of the cluster where the job is running (if slurm is used)
    #   - simulation_type: shieldhit / Fluka / TOPAS
    # some of the stuff above is in the user/simulation endpoint
    '''
    "input_type" : "editor", // or "files"
    "input_files": { // always present, we may either get it from UI or we need to generate it using backend
		"beam.dat": "\nRNDSEED      \t89736501     ! Random seed\nJPART0       \t2            ! Incident particle type\nTMAX0      \t150.0 1.5       ! Incident energy and energy spread; both in (MeV/nucl)\nTCUT0 0 1000  ! energy cutoffs [MeV]\nNSTAT       10000    0       ! NSTAT, Step of saving\nSTRAGG          2            ! Straggling: 0-Off 1-Gauss, 2-Vavilov\nMSCAT           2            ! Mult. scatt 0-Off 1-Gauss, 2-Moliere\nNUCRE           1            ! Nucl.Reac. switcher: 1-ON, 0-OFF\nBEAMPOS 0 0 0 ! Position of the beam\nBEAMDIR 0.0 0.0 ! Direction of the beam\nBEAMSIGMA  0 0  ! Beam extension\n! no BEAMSAD value\nDELTAE   0.03   ! relative mean energy loss per transportation step\n",
		"detect.dat": "Geometry Cyl\n    Name CylZ_Mesh\n    R 0 5 1\n    Z 0 20 400\n\nGeometry Mesh\n    Name YZ_Mesh\n    X -0.25 0.25 1\n    Y -2 2 80\n    Z 0 20 400\n\nGeometry Cyl\n    Name EntrySlab\n    R 0 5 1\n    Z 0 0.1 1\n\nGeometry Cyl\n    Name PeakSlab\n    R 0 5 1\n    Z 15.3 15.4 1\n\nFilter\n    Name Protons\n    Z == 1\n    A == 1\nFilter\n    Name Primaries\n    Z == 1\n    A == 1\n    GEN == 0\nFilter\n    Name Secondary_protons\n    Z == 1\n    A == 1\n    GEN >= 1\nOutput\n    Filename z_profile.bdo\n    Geo CylZ_Mesh\n    Quantity Dose \n    Quantity Fluence Protons\n    Quantity Fluence Primaries\n    Quantity Fluence Secondary_protons\n\nOutput\n    Filename yz_profile.bdo\n    Geo YZ_Mesh\n    Quantity Dose \n    Quantity Fluence Protons\n    Quantity Fluence Secondary_protons\n\nOutput\n    Filename entrance.bdo\n    Geo EntrySlab\n    Quantity Dose \n    Quantity AvgEnergy Primaries\n    Quantity AvgEnergy Protons\n    Quantity AvgEnergy Secondary_protons\n    Quantity dLET Protons\n    Quantity tLET Protons\n    Quantity Fluence Protons\n    Diff1 0 160 640 \n    Diff1Type E\n\nOutput\n    Filename peak.bdo\n    Geo PeakSlab\n    Quantity Dose \n    Quantity AvgEnergy Primaries\n    Quantity AvgEnergy Protons\n    Quantity AvgEnergy Secondary_protons\n    Quantity dLET Protons\n    Quantity tLET Protons\n    Quantity Fluence Protons\n    Diff1 0 160 640 \n    Diff1Type E\n",
		"geo.dat": "\n    0    0          Proton pencil beam in water\n  RCC    1       0.0       0.0       0.0       0.0       0.0      20.0\n                 5.0\n  RCC    2       0.0       0.0      -0.5       0.0       0.0      22.0\n                 5.5\n  RCC    3       0.0       0.0      -1.5       0.0       0.0      24.0\n                 6.0\n  END\n  001          +1\n  002          +2     -1\n  003          +3     -1     -2\n  END\n    1    2    3\n    1 1000    0\n",
		"info.json": "{'version': 'unknown', 'label': 'development', 'simulator': 'shieldhit'}",
		"mat.dat": "MEDIUM 1\nICRU 276\nEND\n"
	},
	"input_json": { // this key won't be here, if user submitted simulation using input files
		"beam": {
        }
    }
    '''

    resp = client_fixture.get("/inputs", 
                              query_string={"job_id": job_id})
    data = json.loads(resp.data.decode())
    assert {"message", "input"} == set(data.keys())
    assert {"input_type", "input_files", "input_json", "number_of_all_primaries"} == set(data["input"].keys())
    
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
        if data['job_state'] == 'COMPLETED':
            break
        sleep(1)

    # currently celery cannot communicate with the flask app
    # because of that it cannot send back the results making
    # them inaccesible -> TODO: fix this

    # logging.info("Fetching results from /results endpoint")
    # resp = client_fixture.get("/results",
    #                           query_string={"job_id": job_id})
    # data: dict = json.loads(resp.data.decode())

    # assert resp.status_code == 200  # skipcq: BAN-B101
    # assert {"message", "estimators"} == set(data.keys())
