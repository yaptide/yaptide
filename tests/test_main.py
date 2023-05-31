import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app


@pytest.fixture
def app():
    """Fixture for the app."""
    _app = create_app()
    with _app.app_context():
        db.create_all()
    yield _app

    with _app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    """Fixture for the test client."""
    _client = app.test_client()
    yield _client


def test_app_started(client):
    """Test if the app started."""
    resp = client.get("/")

    assert resp.json['message'] == 'Hello world!'
