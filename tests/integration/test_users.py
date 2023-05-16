import logging
from typing import Generator
from flask import Flask
import pytest
from yaptide.persistence.database import db
from yaptide.application import create_app
from time import sleep
import json

_Username = "test_user"
_Username_2 = "not_existing_user"
_Password = "test_password"


def test_register(client_fixture):
    """Test if user can register"""
    resp = client_fixture.put("/auth/register",
                              data=json.dumps(dict(username=_Username, password=_Password)),
                              content_type='application/json')

    assert resp.status_code == 201  # skipcq: BAN-B101


def test_register_existing(client_fixture):
    """Test if user can register"""
    client_fixture.put("/auth/register",
                       data=json.dumps(dict(username=_Username, password=_Password)),
                       content_type='application/json')
    resp = client_fixture.put("/auth/register",
                              data=json.dumps(dict(username=_Username, password=_Password)),
                              content_type='application/json')

    assert resp.status_code == 403  # skipcq: BAN-B101


def test_log_in(client_fixture):
    """Test if user can log in"""
    client_fixture.put("/auth/register",
                       data=json.dumps(dict(username=_Username, password=_Password)),
                       content_type='application/json')
    resp = client_fixture.post("/auth/login",
                               data=json.dumps(dict(username=_Username, password=_Password)),
                               content_type='application/json')

    assert resp.status_code == 202  # skipcq: BAN-B101
    assert resp.headers['Set-Cookie']  # skipcq: BAN-B101


def test_log_in_not_existing(client_fixture):
    """Test if user can log in"""
    resp = client_fixture.post("/auth/login",
                               data=json.dumps(dict(username=_Username_2, password=_Password)),
                               content_type='application/json')

    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status(client_fixture):
    """Test checking user's status"""
    resp = client_fixture.put("/auth/register",
                              data=json.dumps(dict(username=_Username, password=_Password)),
                              content_type='application/json')
    resp = client_fixture.post("/auth/login",
                               data=json.dumps(dict(username=_Username, password=_Password)),
                               content_type='application/json')

    sleep(10)

    resp = client_fixture.get("/auth/status")

    data = json.loads(resp.data.decode())

    assert data.get('username') == _Username  # skipcq: BAN-B101
    assert resp.status_code == 200  # skipcq: BAN-B101


def test_user_status_unauthorized(client_fixture):
    """Test checking user's status"""
    resp = client_fixture.get("/auth/status")
    logging.info(resp.data)
    assert resp.status_code == 401  # skipcq: BAN-B101


def test_user_status_after_logout(client_fixture):
    """Test checking user's status"""
    client_fixture.put("/auth/register",
                       data=json.dumps(dict(username=_Username, password=_Password)),
                       content_type='application/json')
    client_fixture.post("/auth/login",
                        data=json.dumps(dict(username=_Username, password=_Password)),
                        content_type='application/json')

    sleep(10)

    resp = client_fixture.get("/auth/status")

    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client_fixture.delete("/auth/logout")

    assert resp.status_code == 200  # skipcq: BAN-B101

    resp = client_fixture.get("/auth/status")

    assert resp.status_code == 401  # skipcq: BAN-B101
