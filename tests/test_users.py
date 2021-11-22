import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app
import json

_Login_name = "login123456"
_Password = "password123456"


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

    print(resp.data.decode())
    data = json.loads(resp.data.decode())

    assert data.get('status') == 'SUCCESS'  # skipcq: BAN-B101


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

    data = json.loads(resp.data.decode())

    assert data.get('status') == 'ERROR'  # skipcq: BAN-B101


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

    data = json.loads(resp.data.decode())

    assert data.get('status') == 'SUCCESS'  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101


def test_log_in_not_existing(client):
    """Test if user can log in"""
    resp = client.post("/auth/login", data=json.dumps(dict(
        login_name=_Login_name,
        password=_Password)),
        content_type='application/json')

    data = json.loads(resp.data.decode())

    assert data.get('status') == 'ERROR'  # skipcq: BAN-B101
