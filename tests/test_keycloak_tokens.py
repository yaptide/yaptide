import jwt
import json
import pytest
import os
from unittest.mock import patch

from yaptide.routes.keycloak_routes import check_user_based_on_keycloak_token
from werkzeug.exceptions import Forbidden, Unauthorized


@pytest.fixture(scope='module')
def token() -> str:
    """Username for user with invalid password"""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiaWF0IjoxNTE2MjM5MDIyLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiJwbGd0ZXN0dXNlciIsInR5cCI6IkJlYXJlciIsImF6cCI6InlhcHRpZGUtc3RhZ2luZyIsImF1ZCI6WyJzb21lX2F1ZGllbmNlLnhEIiwiYW5vdGhlcl9hdWRpZW5jZS54RCJdfQ.koeS9Xu5ueOQ282TANB2jKjIUxo9vZXioDpMUgmv9G8"


def test_token_not_provided():
    """Test token not provided"""
    with pytest.raises(Unauthorized) as e:
        check_user_based_on_keycloak_token("", "test")
    assert e.match("No token provided")


def test_keycloak_url_not_set(token):
    """Test keycloak url not set"""
    with pytest.raises(Forbidden) as e:
        check_user_based_on_keycloak_token(token, "test")
    assert e.match("Service is not available")


def test_username_not_matching(token):
    """Test username mismatch"""
    # set dummy keycloak env variables to bypass Forbidden exception
    with patch.dict(os.environ, {
        "KEYCLOAK_BASE_URL": "http://localhost:8080",
        "KEYCLOAK_REALM": "yaptide"}):
        with pytest.raises(Forbidden) as e:
            check_user_based_on_keycloak_token(token, "test")
        assert e.match("Username mismatch")
