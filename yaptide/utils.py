from datetime import datetime, timedelta
from typing import Union
from secrets import token_hex

import jwt

SECRET_KEY_TOKEN = token_hex(64)
SECRET_KEY_TOKEN_REFRESH = token_hex(64)
Refresh_Token_Expiration_Time = 7200
Token_Expiration_Time = 600


def encode_auth_token(user_id: int, isRefresh: bool = False) -> tuple[Union[str, Exception], datetime]:
    """Function encoding the token"""
    if isRefresh:
        secret = SECRET_KEY_TOKEN_REFRESH
        exp_time_minutes = Refresh_Token_Expiration_Time
    else:
        secret = SECRET_KEY_TOKEN
        exp_time_minutes = Token_Expiration_Time
    exp = datetime.utcnow() + timedelta(seconds=exp_time_minutes)
    try:
        payload = {
            'exp': exp,
            'iat': datetime.utcnow(),
            'sub': user_id
        }
        return jwt.encode(payload, secret, algorithm='HS256'), exp
    except Exception as e:  # skipcq: PYL-W0703
        return e, exp


def decode_auth_token(token: str, isRefresh: bool = False) -> Union[int, str]:
    """Function decoding the token"""
    if isRefresh:
        secret = SECRET_KEY_TOKEN_REFRESH
    else:
        secret = SECRET_KEY_TOKEN

    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload['sub']
    except jwt.ExpiredSignatureError:
        return 'Signature expired'
    except jwt.InvalidTokenError:
        return 'Invalid token'
