import requests

import pytest

from yaptide import create_test_app
from yaptide import db, models

BASEURL = "http://127.0.0.1:5000/"


@pytest.fixture
def app():
    app = create_test_app()
    db.create_all()
    yield app
    db.session.remove()
    db.drop_all()


def test_create_example_user(app):
    response = requests.put(BASEURL + "example_user", {"name": "qwe123"})
    assert response.json()["name"] == "qwe123"


def test_get_user(app):
    db
