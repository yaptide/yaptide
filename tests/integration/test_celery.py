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
import numpy as np
import pytest  # skipcq: PY-W2000

from celery import group, chord

# note that the imports below will in turn call `from yaptide.celery.worker import celery_app`
# that will create a `celery_app` instance
from yaptide.celery.tasks import run_single_simulation, merge_results
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries
from celery.contrib.pytest import celery_app, celery_worker, celery_config, celery_parameters,celery_enable_logging, use_celery_app_trap, celery_includes, celery_worker_pool, celery_worker_parameters


@pytest.mark.usefixtures("live_server", "live_server_win")
def test_celery_run_simulation_for_shieldhit(celery_app, celery_worker, payload_editor_dict_data: dict, client,
                                             add_simulators_to_path_variable, modify_tmpdir,
                                             shieldhit_binary_installed):
    """Test run_simulation task with SHIELD-HIT12A binary
    Current Windows demo version version of SHIELD-HIT12A has a bug, so it cannot parse more elaborated input files.
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
        payload_dict["input_json"]["scoringManager"]["filters"] = []
        payload_dict["input_json"]["detectorManager"]["detectors"] = [
            payload_dict["input_json"]["detectorManager"]["detectors"][0]
        ]
        payload_dict["input_json"]["scoringManager"]["outputs"] = [
            payload_dict["input_json"]["scoringManager"]["outputs"][0]
        ]
        for output in payload_dict["input_json"]["scoringManager"]["outputs"]:
            for quantity in output["quantities"]:
                if "filter" in quantity:
                    del quantity["filter"]

    files_dict, _ = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
    logging.info("Starting run_simulation task")

    map_group = group([
        run_single_simulation.s(
            files_dict=files_dict,
            task_id=i + 1,
            keep_tmp_files=True,  # lets pytest to clean up the tmp files, last 3 directories will be kept
            sim_type='shieldhit') for i in range(payload_dict["ntasks"])
    ])

    workflow = chord(map_group, merge_results.s())
    job = workflow.delay()
    logging.info("Waiting for run_simulation task to finish")
    result: dict = job.wait()
    logging.info("run_simulation task finished")
    assert 'logfiles' not in result.keys()
    assert 'estimators' in result.keys()


@pytest.fixture(scope='module')
def expected_fluka_mock_results() -> dict:
    """Return expected result"""
    yield {
        "21": {
            "4x4": [[0., 0., 0., 0.], [0., 1.46468, 1.69978, 0.], [0.9081, 0., 0., 0.], [0, 0., 0., 0.]]
        },
        "22": {
            "4x4": [[0.4757, 0., 0., 0.], [0., 1.88021, 1.66488, 0.], [0., 1.0242, 1.05254, 0.], [0., 0., 0., 0.]]
        }
    }


@pytest.mark.skipif(platform.system() == "Windows", reason="FLUKA mock is not supported on Windows")
@pytest.mark.usefixtures("live_server")
def test_celery_run_simulation_for_fluka_mock(celery_app, celery_worker, payload_editor_dict_data_fluka: dict, client,
                                              add_simulator_mocks_to_path_variable, modify_tmpdir,
                                              expected_fluka_mock_results):
    """Test run_simulation task with FLUKA mock binary"""
    # lets make a local copy of the payload dict, so we don't modify the original one
    payload_dict = copy.deepcopy(payload_editor_dict_data_fluka)
    # limit the particle numbers to get faster results
    payload_dict["input_json"]["beam"]["numberOfParticles"] = 12
    payload_dict["ntasks"] = 2

    files_dict, _ = files_dict_with_adjusted_primaries(payload_dict=payload_dict)

    logging.info("Starting run_simulation task")

    map_group = group([
        run_single_simulation.s(
            files_dict=files_dict,
            task_id=i + 1,
            keep_tmp_files=True,  # lets pytest to clean up the tmp files, last 3 directories will be kept
            sim_type='fluka') for i in range(payload_dict["ntasks"])
    ])

    workflow = chord(map_group, merge_results.s())
    job = workflow.delay()
    logging.info("Waiting for run_simulation task to finish")
    result: dict = job.wait()
    logging.info("run_simulation task finished")
    assert 'logfiles' not in result
    assert 'estimators' in result
    estimators = result['estimators']
    assert len(estimators) == 2
    sorted_estimators = sorted(estimators, key=lambda x: x['name'])
    estimator_21 = sorted_estimators[0]
    estimator_22 = sorted_estimators[1]
    assert estimator_21['name'] == '21'
    assert estimator_22['name'] == '22'
    for estimator in sorted_estimators:
        name = estimator['metadata']['file_corename']
        assert len(estimator['pages']) == 1
        __verify_fluka_file(estimator['pages'][0], expected_fluka_mock_results[name]['4x4'])


def __verify_fluka_file(actual_page: dict, expected_page: dict):
    """Compares content of generated fluka file with expected values"""
    expected = list(np.around(np.swapaxes(np.array(expected_page), 0, 1).flatten(), 4))
    result = list(np.around(np.flip(np.array(actual_page['data']['values']), []).flatten(), 4))
    assert expected == result, "Fluka data does not match expected values"
