"""
Unit tests for celery tasks
By default celery uses redis as a broker and backend, which requires to run external redis server.
This is somehow problematic to run in CI, so we use in-memory backend and rpc broker.

We also use celery fixture from pytest-celery plugin, which starts celery worker in a separate thread.
This fixture is silencing most of the logging. To see the logs, use:
pytest tests/integration/test_celery.py -o log_cli=1 -o log_cli_level=DEBUG -s
"""
import copy
import logging
import platform
import pytest  # skipcq: PY-W2000

# note that the imports below will in turn call `from yaptide.celery.worker import celery_app`
# that will create a `celery_app` instance
from yaptide.celery.tasks import cancel_simulation, run_simulation
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries


def test_run_simulation(celery_app, 
                        celery_worker, 
                        payload_editor_dict_data : dict, 
                        client_fixture,
                        add_directory_to_path,
                        shieldhit_demo_binary):
    """Test run_simulation task with SHIELDHIT demo binary
    Current Windows demo version version of SHIELDHIT has a bug, so it cannot parse more elaborated input files.
    Parser relies on rewind function, which does not work properly on Windows, see:
    https://stackoverflow.com/questions/47256223/why-does-fseek-0-seek-cur-fail-on-windows/47256758#47256758
    So to bypass this issue we restrict the detect configuration to only one output and no filter.
    Below goes the code which reduces the detect.dat.
    """
    # lets make a local copy of the payload dict, so we don't modify the original one
    payload_dict = copy.deepcopy(payload_editor_dict_data)

    # limit the particle numbers to get faster results
    payload_dict["input_json"]["beam"]["numberOfParticles"] = 12
    payload_dict["ntasks"] = 2

    if platform.system() == "Windows":
        payload_dict["input_json"]["detectManager"]["filters"] = []
        payload_dict["input_json"]["detectManager"]["detectGeometries"] = [payload_dict["input_json"]["detectManager"]["detectGeometries"][0]]
        payload_dict["input_json"]["scoringManager"]["scoringOutputs"] = [payload_dict["input_json"]["scoringManager"]["scoringOutputs"][0]]
        for output in payload_dict["input_json"]["scoringManager"]["scoringOutputs"]:
            for quantity in output["quantities"]["active"]:
                if "filter" in quantity:
                    del quantity["filter"]

    files_dict, _ = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
    logging.info("Starting run_simulation task")
    job = run_simulation.delay(payload_dict=payload_dict, files_dict=files_dict)
    logging.info("Waiting for run_simulation task to finish")
    result: dict = job.wait()
    logging.info("run_simulation task finished")
    assert 'result' in result.keys()


def test_cancel_simulation(celery_app, 
                           celery_worker, 
                           client_fixture,
                           payload_editor_dict_data: dict):
    """Right now cancel_simulation task does nothing, so it should return False"""
    job = cancel_simulation.delay(job_id="test")
    result: dict = job.wait()
    logging.info('Number of particles in the simulation: %d', payload_editor_dict_data["input_json"]["beam"]["numberOfParticles"])
    assert result is False