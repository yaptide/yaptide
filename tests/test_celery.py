import pytest
from celery.contrib.testing.tasks import ping

from yaptide.celery.tasks import cancel_simulation

@pytest.fixture(scope='session')
def celery_app(request):
    from yaptide.celery.worker import celery_app as app
    return app


def test_cancel_simulation(celery_app, celery_worker):
    job = cancel_simulation.delay(job_id="test")
    result: dict = job.wait()
    assert result == False