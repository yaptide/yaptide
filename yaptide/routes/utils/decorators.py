from functools import wraps
from typing import Union

from flask import request
from sqlalchemy.orm import with_polymorphic
from werkzeug.exceptions import Forbidden, Unauthorized

from yaptide.persistence.database import db
from yaptide.persistence.models import KeycloakUserModel, UserBaseModel, YaptideUserModel
from yaptide.routes.utils.tokens import decode_auth_token


def requires_auth(is_refresh: bool = False):
    """Decorator for auth requirements"""
    def decorator(f):
        """Determines if the access or refresh token is valid"""
        @wraps(f)
        def wrapper(*args, **kwargs):
            token: str = request.cookies.get('refresh_token' if is_refresh else 'access_token')
            if not token:
                raise Unauthorized(description="No token provided")
            resp: Union[int, str] = decode_auth_token(token=token, is_refresh=is_refresh)
            if isinstance(resp, int):
                UserPoly = with_polymorphic(UserBaseModel, [YaptideUserModel, KeycloakUserModel])
                user = db.session.query(UserPoly).filter_by(id=resp).first()
                if user:
                    return f(user, *args, **kwargs)
                raise Forbidden(description="User not found")
            if is_refresh:
                raise Forbidden(description="Log in again")
            raise Forbidden(description="Refresh access token")
        return wrapper
    return decorator
