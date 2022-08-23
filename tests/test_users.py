import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app
from time import sleep
import json

_Login_name = "test_user"
_Password = "test_password"


@pytest.fixture
def app():  # skipcq: PY-D0003
    _app = create_app()
    with _app.app_context():
        db.create_all()
    yield _app
    db.session.remove()
    with _app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):  # skipcq: PY-D0003
    _client = app.test_client()
    yield _client


def test_register(client):
    """Test if user can register"""
    resp = client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    assert resp.status_code == 201  # skipcq: BAN-B101


def test_register_existing(client):
    """Test if user can register"""
    client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')
    resp = client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    assert resp.status_code == 403  # skipcq: BAN-B101


def test_log_in(client):
    """Test if user can log in"""
    client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')
    resp = client.post("/auth/login", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101


def test_log_in_not_existing(client):
    """Test if user can log in"""
    resp = client.post("/auth/login", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status(client):
    """Test checking user's status"""
    resp = client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')
    resp = client.post("/auth/login", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    sleep(10)

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())

    assert data.get('login_name') == _Login_name  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101


def test_user_status_unauthorized(client):
    """Test checking user's status"""
    resp = client.get("/auth/status")

    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status_after_logout(client):
    """Test checking user's status"""
    client.put("/auth/register", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')
    client.post("/auth/login", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    sleep(10)

    resp = client.get("/auth/status")

    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.delete("/auth/logout")

    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.get("/auth/status")

    assert resp.status_code == 401  # skipcq: BAN-B101
