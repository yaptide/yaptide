import pytest
from werkzeug.exceptions import Forbidden, Unauthorized
from yaptide.routes.keycloak_routes import check_user_based_on_keycloak_token

@pytest.fixture(scope="function")
def keycloak_environment(monkeypatch):
    """Set keycloak environment variables"""
    monkeypatch.setenv("KEYCLOAK_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("KEYCLOAK_REALM", "yaptide")


@pytest.fixture(scope='module')
def token() -> str:
    """
    Keycloak dummy token, constructed using https://jwt.io site
    This token contains "preferred_username": "plgtestuser"
    """
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiaWF0IjoxNTE2MjM5MDIyLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiJwbGd0ZXN0dXNlciIsInR5cCI6IkJlYXJlciIsImF6cCI6InlhcHRpZGUtc3RhZ2luZyIsImF1ZCI6WyJzb21lX2F1ZGllbmNlLnhEIiwiYW5vdGhlcl9hdWRpZW5jZS54RCJdfQ.koeS9Xu5ueOQ282TANB2jKjIUxo9vZXioDpMUgmv9G8"


def test_cannot_connect(token, keycloak_environment):
    """Test token not provided"""
    with pytest.raises(Forbidden) as e:
        check_user_based_on_keycloak_token(token=token, username="plgtestuser")
    assert e.match("Service is not available")


def test_token_not_provided():
    """Test token not provided"""
    with pytest.raises(Unauthorized) as e:
        check_user_based_on_keycloak_token(token="", username="test")
    assert e.match("No token provided")


def test_keycloak_url_not_set(token):
    """Test keycloak url not set"""
    with pytest.raises(Forbidden) as e:
        check_user_based_on_keycloak_token(token, username="test")
    assert e.match("Service is not available")


def test_username_not_matching(token, keycloak_environment):
    """Test username mismatch"""
    with pytest.raises(Forbidden) as e:
        check_user_based_on_keycloak_token(token, "test")
    assert e.match("Username mismatch")
