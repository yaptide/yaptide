"""
Unit tests for celery tasks
By default celery uses redis as a broker and backend, which requires to run external redis server.
This is somehow problematic to run in CI, so we use in-memory backend and rpc broker.

We also use celery fixture from pytest-celery plugin, which starts celery worker in a separate thread.
This fixture is silencing most of the logging. To see the logs, use:
WORKER_LOGLEVEL=debug pytest tests/test_celery.py -o log_cli=1 -o log_cli_level=DEBUG -s
"""

import logging
import pytest

from yaptide.celery.tasks import cancel_simulation, run_simulation


@pytest.fixture(scope='module')
def celery_app():
    from yaptide.celery.worker import celery_app as app
    return app


'''
def start_worker(
    app,  # type: Celery
    concurrency=1,  # type: int
    pool='solo',  # type: str
    loglevel=WORKER_LOGLEVEL,  # type: Union[str, int]
    logfile=None,  # type: str
    perform_ping_check=True,  # type: bool
    ping_task_timeout=10.0,  # type: float
    shutdown_timeout=10.0,  # type: float

    # dummy celery worker performs ping tests, 
# if we don't import it, the worker won't be able to find the ping task
# see also https://github.com/celery/celery/issues/4851#issuecomment-604073785
#from celery.contrib.testing.tasks import ping
'''


@pytest.fixture(scope="module")
def celery_worker_parameters():
    return {
        "perform_ping_check": False,
        "concurrency": 1,
    }


def test_run_simulation(celery_app, celery_worker, payload_editor_dict_data, add_directory_to_path,
                        shieldhit_demo_binary):
    payload_editor_dict_data["ntasks"] = 2
    job = run_simulation.delay(payload_dict=payload_editor_dict_data)
    result: dict = job.wait()
    assert 'input_files' in result.keys()
    assert 'result' in result.keys()


def test_cancel_simulation(celery_app, celery_worker):
    """Right now cancel_simulation task does nothing, so it should return False"""
    job = cancel_simulation.delay(job_id="test")
    result: dict = job.wait()
    assert result == False