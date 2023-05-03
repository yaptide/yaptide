import pytest

# dummy celery worker performs ping tests, 
# if we don't import it, the worker won't be able to find the ping task
from celery.contrib.testing.tasks import ping
from yaptide.celery.tasks import cancel_simulation, run_simulation

@pytest.fixture(scope='module')
def celery_app():
    from yaptide.celery.worker import celery_app as app
    return app

def test_run_simulation(celery_app, celery_worker, payload_editor_dict_data):    
    job = run_simulation.delay(payload_dict=payload_editor_dict_data)
    result: dict = job.wait()
    assert result == False

def test_cancel_simulation(celery_app, celery_worker):
    """Right now cancel_simulation task does nothing, so it should return False"""
    job = cancel_simulation.delay(job_id="test")
    result: dict = job.wait()
    assert result == False