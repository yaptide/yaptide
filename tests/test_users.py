import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app

_Email = "test@email.com"
_Password = "123456"


@pytest.fixture
def app():
    _app = create_app()
    with _app.app_context():
        db.create_all()
    yield _app
    db.session.remove()
    with _app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    _client = app.test_client()
    yield _client


def test_register(client):
    """Test if user can register"""
    resp = client.put("/auth/register", data={
        "email": _Email,
        "password": _Password})

    assert resp.status == "OK"  # status is a placeholder -> to be changed


def test_register_existing(client):
    """Test if user can register"""
    client.put("/auth/register", data={
        "email": _Email,
        "password": _Password})
    resp = client.put("/auth/register", data={
        "email": _Email,
        "password": _Password})

    assert resp.status == "ERROR"  # status is a placeholder -> to be changed


def test_log_in(client):
    """Test if user can log in"""
    client.put("/auth/register", data={
        "email": _Email,
        "password": _Password})
    resp = client.post("/auth/login", data={
        "email": _Email,
        "password": _Password})

    assert resp.status == "OK"  # status is a placeholder -> to be changed
    assert resp.json["token"]


def test_log_in_not_existing(client):
    """Test if user can log in"""
    resp = client.post("/auth/login", data={
        "email": _Email,
        "password": _Password})

    assert resp.status == "ERROR"  # status is a placeholder -> to be changed
