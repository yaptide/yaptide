# test_app.py

import pytest
from yaptide.application import create_app
from yaptide.celery.worker import celery_app as celery


@pytest.fixture(scope='module')
def test_client():
    app = create_app('testing')
    with app.test_client() as testing_client:
        with app.app_context():
            yield testing_client


@pytest.fixture(scope='module')
def celery_app(request):
    celery.conf.update(CELERY_ALWAYS_EAGER=True)
    return celery


def test_celery_task(celery_app):
    result = celery_app.send_task('tasks.add', args=[1, 2])
    assert result.get() == 3


def test_redis_connection(test_client):
    response = test_client.get('/redis')
    assert response.status_code == 200
    assert response.data == b'Connection to Redis server succeeded!'
