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


def check_user_based_on_keycloak_token(token: str, username: str) -> bool:
    """Checks if user can access the service, returns True if user has acess"""
    if not token:
        logging.error("No token provided")
        raise Unauthorized(description="No token provided")
    keycloak_base_url = os.environ.get('KEYCLOAK_BASE_URL', '')
    keycloak_realm = os.environ.get('KEYCLOAK_REALM', '')
    if not keycloak_base_url or not keycloak_realm:
        logging.error("Keycloak env variables not set")
        raise Forbidden(description="Service is not available")
    keycloak_full_url = f"{keycloak_base_url}/auth/realms/{keycloak_realm}/protocol/openid-connect/certs"
    try:
        # first lets try to decode token without verifying signature
        unverified_encoded_token = jwt.decode(token, options={"verify_signature": False})
        # very crude way to check by username comparison
        # we will later update this place by checking if use has access to our yaptite platform
        if username != unverified_encoded_token["preferred_username"]:
            logging.error("Username mismatch")
            raise Forbidden(description="Username mismatch")

        # ask keycloak for public keys
        res = requests.get(keycloak_full_url)
        jwks = res.json()

        # get public key for our token, based on kid
        public_keys = {}
        for jwk in jwks['keys']:
            kid = jwk['kid']
            public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        kid = jwt.get_unverified_header(token)['kid']
        key = public_keys[kid]

        # now we can verify signature of the token
        _ = jwt.decode(token,
                       key=key,
                       audience=unverified_encoded_token["aud"],
                       algorithms=['RS256'],
                       options={"verify_signature": True})

        return True

    except jwt.ExpiredSignatureError as e:
        logging.error("Signature expired: %s", e)
        raise Forbidden(description="Signature expired")
    except jwt.InvalidTokenError as e:
        logging.error("Invalid token: %s", e)
        raise Forbidden(description="Invalid token")
    except requests.exceptions.ConnectionError as e:
        logging.error("Unable to connect to keycloak: %s", e)
        raise Forbidden(description="Service is not available")


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

        username = payload_dict["username"]
        logging.debug("Authenticating for user: %s", username)
        keycloak_token: str = request.headers.get('Authorization', '')

        # check if user has access to our service, if not throw an exception here
        check_user_based_on_keycloak_token(keycloak_token.replace('Bearer ', ''), username)

        # ask cert auth service for cert and private key
        session = requests.Session()
        res: requests.Response = session.get(cert_auth_url, headers={
            'Authorization': keycloak_token
        })
        res_json: dict = res.json()
        logging.debug("auth cert service response code: %d", res.status_code)
        logging.debug("auth cert service response mesg: %s", res_json)

        # check if user exists in our database, if not create new user
        user = fetch_keycloak_user_by_username(username=username)
        if not user:
            # user not existing, adding user together with cert and private key
            user = KeycloakUserModel(username=username,
                                     cert=res_json["cert"],
                                     private_key=res_json["private"])

            add_object_to_db(user)
        else:
            # user existing, updating cert and private key
            user.cert = res_json["cert"]
            user.private_key = res_json["private"]
            make_commit_to_db()

        try:
            # prepare our own tokens
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
