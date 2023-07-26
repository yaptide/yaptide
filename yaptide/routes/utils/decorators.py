from typing import Union
from flask import request
from werkzeug.exceptions import Unauthorized, Forbidden

from functools import wraps

from yaptide.persistence.database import db
from yaptide.persistence.models import YaptideUserModel, KeycloakUserModel

from yaptide.routes.utils.tokens import decode_auth_token


def requires_auth(is_refresh: bool = False, is_keycloak: bool = False):
    """Decorator for auth requirements"""
    def decorator(f):
        """Determines if the access or refresh token is valid"""
        @wraps(f)
        def wrapper(*args, **kwargs):
            token: str = request.cookies.get('refresh_token' if is_refresh else 'access_token')
            if not token:
                raise Unauthorized(description="No token provided")
            resp: Union[int, str] = decode_auth_token(token=token,
                                                      is_refresh=is_refresh,
                                                      is_keycloak=is_keycloak)
            if isinstance(resp, int):
                if is_keycloak:
                    user = db.session.query(KeycloakUserModel).filter_by(id=resp).first()
                else:
                    user = db.session.query(YaptideUserModel).filter_by(id=resp).first()
                if user:
                    return f(user, *args, **kwargs)
                raise Forbidden(description="User not found")
            if is_refresh:
                raise Forbidden(description="Log in again")
            raise Forbidden(description="Refresh access token")
        return wrapper
    return decorator
