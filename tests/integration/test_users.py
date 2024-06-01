import json

import pytest  # skipcq: PY-W2000


def test_register(client, db_good_username: str, db_good_password: str):
    """Test if user can register"""
    resp = client.put("/auth/register",
                      data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                      content_type='application/json')

    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 201  # skipcq: BAN-B101


def test_register_existing(client, db_good_username: str, db_good_password: str):
    """Test if user can register"""
    client.put("/auth/register",
               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
               content_type='application/json')
    resp = client.put("/auth/register",
                      data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                      content_type='application/json')

    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 403  # skipcq: BAN-B101


def test_log_in(client, db_good_username: str, db_good_password: str):
    """Test if user can log in"""
    client.put("/auth/register",
               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
               content_type='application/json')
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')

    data = json.loads(resp.data.decode())
    assert {'refresh_exp', 'access_exp', 'message'} == set(data.keys())
    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101


def test_log_in_not_existing(client, db_good_username: str, db_good_password: str):
    """Test if user can log in"""
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')

    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status(client, db_good_username: str, db_good_password: str):
    """Test checking user's status"""
    resp = client.put("/auth/register",
                      data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                      content_type='application/json')
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {'message', 'username'} == set(data.keys())
    assert data['username'] == db_good_username  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101


def test_user_status_unauthorized(client):
    """Test checking user's status"""
    resp = client.get("/auth/status")
    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status_after_logout(client, db_good_username: str, db_good_password: str):
    """Test checking user's status"""
    client.put("/auth/register",
               data=json.dumps(dict(username=db_good_username, password=db_good_password)),
               content_type='application/json')
    client.post("/auth/login",
                data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                content_type='application/json')

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {'message', 'username'} == set(data.keys())
    assert data['username'] == db_good_username  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.delete("/auth/logout")

    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {'message'} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101
