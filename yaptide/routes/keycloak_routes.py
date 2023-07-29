import logging
import os
from pathlib import Path

import requests

from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import KeycloakUserModel

from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response


ROOT_DIR = Path(__file__).parent.resolve()


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
        if not keycloak_token:
            return yaptide_response(message='No keycloak token provided', code=401)

        session = requests.Session()
        res: requests.Response = session.get(cert_auth_url, headers={
            'Authorization': keycloak_token
        })
        res_json: dict = res.json()
        logging.warning(res.status_code)
        logging.warning("%s", res_json)

        username = payload_dict["username"]
        logging.warning("Got username %s", username)

        user: KeycloakUserModel = db.session.query(KeycloakUserModel).filter_by(username=username).first()
        if not user:
            user = KeycloakUserModel(username=username,
                                     cert=res_json["cert"],
                                     private_key=res_json["private"])

            db.session.add(user)
        else:
            user.cert = res_json["cert"]
            user.private_key = res_json["private"]

        db.session.commit()

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
