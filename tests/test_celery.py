"""
Unit tests for celery tasks
By default celery uses redis as a broker and backend, which requires to run external redis server.
This is somehow problematic to run in CI, so we use in-memory backend and rpc broker.

We also use celery fixture from pytest-celery plugin, which starts celery worker in a separate thread.
This fixture is silencing most of the logging. To see the logs, use:
WORKER_LOGLEVEL=debug pytest tests/test_celery.py -o log_cli=1 -o log_cli_level=DEBUG -s
"""
import platform
import pytest

# note that the imports below will in turn call `from yaptide.celery.worker import celery_app`
# that will create a `celery_app` instance
from yaptide.celery.tasks import cancel_simulation, run_simulation


@pytest.fixture(scope='module')
def celery_app():
    """
    Create celery app for testing, we reuse the one from yaptide.celery.worker module.
    The choice of broker and backend is important, as we don't want to run external redis server.
    That is being configured via environment variables in pytest.ini file.
    """
    from yaptide.celery.worker import celery_app as app
    return app


@pytest.fixture(scope="module")
def celery_worker_parameters():
    """
    Default celery worker parameters cause problems with finding "ping task" module, as being described here:
    https://github.com/celery/celery/issues/4851#issuecomment-604073785
    To solve that issue we disable the ping check.
    Another solution would be to do `from celery.contrib.testing.tasks import ping` but current one is more elegant.

    Here we could as well configure other fixture worker parameters, like app, pool, loglevel, etc.
    """
    return {
        "perform_ping_check": False,
        "concurrency": 1
    }

def test_run_simulation(celery_app, celery_worker, payload_editor_dict_data, add_directory_to_path,
                        shieldhit_demo_binary):
    """
    Test run_simulation task with SHIELDHIT demo binary
    Current Windows demo version version of SHIELDHIT has a bug, so it cannot parse more elaborated input files.
    Parser relies on rewind function, which does not work properly on Windows, see:
    https://stackoverflow.com/questions/47256223/why-does-fseek-0-seek-cur-fail-on-windows/47256758#47256758
    So to bypass this issue we restrict the detect configuration to only one output and no filter.
    Below goes the code which reduces the detect.dat.
    """
    
    payload_editor_dict_data["ntasks"] = 1

    if platform.system() == "Windows":
        payload_editor_dict_data["sim_data"]["detectManager"]["filters"] = []
        payload_editor_dict_data["sim_data"]["detectManager"]["detectGeometries"] = [payload_editor_dict_data["sim_data"]["detectManager"]["detectGeometries"][0]]
        payload_editor_dict_data["sim_data"]["scoringManager"]["scoringOutputs"] = [payload_editor_dict_data["sim_data"]["scoringManager"]["scoringOutputs"][0]]
        for output in payload_editor_dict_data["sim_data"]["scoringManager"]["scoringOutputs"]:
            for quantity in output["quantities"]["active"]:
                if "filter" in quantity:
                    del quantity["filter"]

    job = run_simulation.delay(payload_dict=payload_editor_dict_data)
    result: dict = job.wait()
    assert 'input_files' in result.keys()
    assert 'result' in result.keys()


def test_cancel_simulation(celery_app, celery_worker):
    """Right now cancel_simulation task does nothing, so it should return False"""
    job = cancel_simulation.delay(job_id="test")
    result: dict = job.wait()
    assert result is False