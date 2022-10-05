import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app


@pytest.fixture
def app():
    _app = create_app()
    with _app.app_context():
        db.create_all()
    yield _app
    # db.session.remove()
    with _app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    _client = app.test_client()
    yield _client


def test_app_started(client):
    resp = client.get("/")

    assert resp.json['message'] == 'Hello world!'
