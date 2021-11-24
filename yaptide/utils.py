import datetime
import jwt
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY_TOKEN = os.getenv('SECRET_KEY_TOKEN')
SECRET_KEY_TOKEN_REFRESH = os.getenv('SECRET_KEY_TOKEN_REFRESH')
Refresh_Token_Expiration_Time = 7200
Token_Expiration_Time = 600


def encode_auth_token(user_id, isRefresh: bool):
    """
    Generates the Auth Token
    :return: string
    """
    if isRefresh:
        secret = SECRET_KEY_TOKEN_REFRESH
        exp_time_minutes = Refresh_Token_Expiration_Time
    else:
        secret = SECRET_KEY_TOKEN
        exp_time_minutes = Token_Expiration_Time

    try:
        payload = {
            'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=exp_time_minutes),
            'iat': datetime.datetime.utcnow(),
            'sub': user_id
        }
        return jwt.encode(
            payload,
            secret,
            algorithm='HS256'
        )
    except Exception as e:  # skipcq: PYL-W0703
        return e


def decode_auth_token(token, isRefresh: bool):
    """
    Decodes the auth token
    :param token:
    :return: integer|string
    """
    if isRefresh:
        secret = SECRET_KEY_TOKEN_REFRESH
    else:
        secret = SECRET_KEY_TOKEN

    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload['sub']
    except jwt.ExpiredSignatureError:
        return 'Signature expired. Please log in again.'
    except jwt.InvalidTokenError:
        return 'Invalid token. Please log in again.'
