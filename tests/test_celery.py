import pytest

# tasks.py
from celery import Celery, shared_task
from yaptide.celery.tasks import cancel_simulation

# Define the Celery app
celery_app = Celery(
    'tasks',
    broker='memory://',
    backend='rpc://',
)

# Register the Celery app with pytest
@pytest.fixture(scope='session')
def app():
    return celery_app

@shared_task
def mul(x, y):
    return x * y

# def test_mul(celery_app, celery_worker):    
#     assert mul.delay(4, 4).get(timeout=10) == 16

#@pytest.mark.celery(result_backend='rpc', broker_url='memory://')
def test_cancel_simulation(celery_app, celery_worker):
    assert cancel_simulation.delay("test").get(timeout=1) == True