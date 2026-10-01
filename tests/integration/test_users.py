import json

import pytest  # skipcq: PY-W2000


def test_register(client, db_good_username: str, db_good_password: str):
    """Test if user can register"""
    resp = client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 201  # skipcq: BAN-B101


def test_register_existing(client, db_good_username: str, db_good_password: str):
    """Test if user can register"""
    client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    resp = client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 403  # skipcq: BAN-B101


def test_log_in(client, db_good_username: str, db_good_password: str):
    """Test if user can log in"""
    client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    resp = client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    data = json.loads(resp.data.decode())
    assert {"refresh_exp", "access_exp", "message"} == set(data.keys())
    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers["Set-Cookie"]  # skipcq: BAN-B101


def test_log_in_not_existing(client, db_good_username: str, db_good_password: str):
    """Test if user can log in"""
    resp = client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status(client, db_good_username: str, db_good_password: str):
    """Test checking user's status"""
    resp = client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    resp = client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {"message", "username"} == set(data.keys())
    assert data["username"] == db_good_username  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101


def test_user_status_unauthorized(client):
    """Test checking user's status"""
    resp = client.get("/auth/status")
    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status_after_logout(client, db_good_username: str, db_good_password: str):
    """Test checking user's status"""
    client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {"message", "username"} == set(data.keys())
    assert data["username"] == db_good_username  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.delete("/auth/logout")

    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client.get("/auth/status")

    data = json.loads(resp.data.decode())
    assert {"message"} == set(data.keys())
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_register_disabled(client, monkeypatch, db_good_username: str, db_good_password: str):
    """Test that registration is rejected when ENABLE_USER_REGISTRATION is false"""
    monkeypatch.setenv("ENABLE_USER_REGISTRATION", "false")
    resp = client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    assert resp.status_code == 403  # skipcq: BAN-B101

    resp = client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_local_users_disabled(client, monkeypatch, db_good_username: str, db_good_password: str):
    """Test that local users can neither register, log in nor use issued tokens when ENABLE_LOCAL_USERS is false"""
    client.put(
        "/auth/register",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    assert client.get("/auth/status").status_code == 200  # skipcq: BAN-B101

    monkeypatch.setenv("ENABLE_LOCAL_USERS", "false")

    resp = client.put(
        "/auth/register",
        data=json.dumps(dict(username=f"{db_good_username}_new", password=db_good_password)),
        content_type="application/json",
    )
    assert resp.status_code == 403  # skipcq: BAN-B101

    resp = client.post(
        "/auth/login",
        data=json.dumps(dict(username=db_good_username, password=db_good_password)),
        content_type="application/json",
    )
    assert resp.status_code == 403  # skipcq: BAN-B101

    # tokens issued before local users were disabled are rejected as well
    assert client.get("/auth/status").status_code == 403  # skipcq: BAN-B101
    assert client.get("/auth/refresh").status_code == 403  # skipcq: BAN-B101
