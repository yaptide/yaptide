from functools import wraps
from typing import Union

from flask import request
from werkzeug.exceptions import Forbidden, Unauthorized

from yaptide.persistence.db_methods import fetch_user_by_id
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.routes.utils.utils import is_disabled_local_user


def requires_auth(is_refresh: bool = False):
    """Decorator for auth requirements"""

    def decorator(f):
        """Determines if the access or refresh token is valid"""

        @wraps(f)
        def wrapper(*args, **kwargs):
            token: str = request.cookies.get("refresh_token" if is_refresh else "access_token")
            if not token:
                raise Unauthorized(description="No token provided")
            resp: Union[int, str] = decode_auth_token(token=token, is_refresh=is_refresh)
            if isinstance(resp, int):
                user = fetch_user_by_id(user_id=resp)
                if user:
                    if is_disabled_local_user(user):
                        raise Forbidden(description="Local users are disabled on this instance")
                    return f(user, *args, **kwargs)
                raise Forbidden(description="User not found")
            if is_refresh:
                raise Forbidden(description=f"Log in again. {resp}")
            raise Forbidden(description=f"Refresh access token. {resp}")

        return wrapper

    return decorator
