import logging
import os
from pathlib import Path

from flask import request
from flask_restful import Resource
import json
import jwt
import requests

from yaptide.persistence.db_methods import (add_object_to_db,
                                            fetch_keycloak_user_by_username,
                                            make_commit_to_db)
from yaptide.persistence.models import KeycloakUserModel
from yaptide.routes.utils.response_templates import (error_internal_response,
                                                     yaptide_response)
from yaptide.routes.utils.tokens import encode_auth_token
from werkzeug.exceptions import Forbidden, Unauthorized

ROOT_DIR = Path(__file__).parent.resolve()


def check_user_based_on_keycloak_token(token: str, username: str) -> str:
    """Checks if user can access the service"""
    if not token:
        logging.error("No token provided")
        raise Unauthorized(description="No token provided")
    keycloak_url = os.environ.get('KEYCLOAK_URL', 'https://sso.pre.plgrid.pl/auth/realms/PLGrid/protocol/openid-connect/certs')
    if not keycloak_url:
        logging.error("KEYCLOAK_URL not set")
        raise Forbidden(description="Service is not available")
    try:
        unverified_encoded_token = jwt.decode(token, options={"verify_signature": False})
        if username != unverified_encoded_token["preferred_username"]:
            logging.error("Username mismatch")
            raise Forbidden(description="Username mismatch")
        res = requests.get(keycloak_url)
        jwks = res.json()

        public_keys = {}
        for jwk in jwks['keys']:
            kid = jwk['kid']
            public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))

        kid = jwt.get_unverified_header(token)['kid']
        key = public_keys[kid]

        _ = jwt.decode(token, key=key, audience=unverified_encoded_token["aud"], algorithms=['RS256'])

        return "yaptide_access"

    except jwt.ExpiredSignatureError:
        logging.error("Signature expired")
        raise Forbidden(description="Signature expired")
    except jwt.InvalidTokenError:
        logging.error("Invalid token")
        raise Forbidden(description="Invalid token")


class AuthKeycloak(Resource):
    """Class responsible for user log in"""

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        cert_auth_url = os.environ.get('CERT_AUTH_URL', '')
        if not cert_auth_url:
            logging.error("CERT_AUTH_URL not set")
            return yaptide_response(message="Service is unavailable, contact with support", code=500)

        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        required_keys = {"username"}

        if required_keys != required_keys.intersection(set(payload_dict.keys())):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        keycloak_token: str = request.headers.get('Authorization', '')

        _ = check_user_based_on_keycloak_token(keycloak_token.replace('Bearer ', ''))

        session = requests.Session()
        res: requests.Response = session.get(cert_auth_url, headers={
            'Authorization': keycloak_token
        })
        res_json: dict = res.json()
        logging.warning(res.status_code)
        logging.warning("%s", res_json)

        username = payload_dict["username"]
        logging.warning("Got username %s", username)

        user = fetch_keycloak_user_by_username(username=username)
        if not user:
            user = KeycloakUserModel(username=username,
                                     cert=res_json["cert"],
                                     private_key=res_json["private"])

            add_object_to_db(user)
        else:
            user.cert = res_json["cert"]
            user.private_key = res_json["private"]
            make_commit_to_db()

        try:
            access_token, access_exp = encode_auth_token(user_id=user.id,
                                                         is_keycloak=True)

            resp = yaptide_response(
                message='Successfully logged in',
                code=202,
                content={
                    'access_exp': int(access_exp.timestamp()*1000),
                }
            )
            resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax', expires=access_exp)
            return resp
        except Exception:  # skipcq: PYL-W0703
            return error_internal_response()

    @staticmethod
    def delete():
        """Method returning status of logging out"""
        resp = yaptide_response(message='User logged out', code=200)
        resp.delete_cookie('access_token')
        return resp
