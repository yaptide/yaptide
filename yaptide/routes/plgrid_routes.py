import logging
from pathlib import Path

import requests

from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import PlgridUserModel, AuthProvider

from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response


ROOT_DIR = Path(__file__).parent.resolve()


class AuthPlgrid(Resource):
    """Class responsible for user log in"""

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        # payload_dict: dict = request.get_json(force=True)
        # if not payload_dict:
        #     return yaptide_response(message="No JSON in body", code=400)

        # required_keys = {"username", "exp"}

        # if required_keys != required_keys.intersection(set(payload_dict.keys())):
        #     diff = required_keys.difference(set(payload_dict.keys()))
        #     return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        keycloak_token: str = request.headers.get('PLGRID', '')
        if not keycloak_token:
            return yaptide_response(message='No plgrid token provided', code=401)

        session = requests.Session()
        res: requests.Response = session.get("https://ccm-dev.kdm.cyfronet.pl/key", headers={
            'Authorization': f'Bearer {keycloak_token}'
        })
        res_json: dict = res.json()
        logging.warning(res.status_code)
        logging.warning("%s", res_json)

        # username = payload_dict["username"]
        username: str = request.headers.get('username', '')
        logging.warning("Got username %s", username)

        public_path = ROOT_DIR / f"id_rsa_{username}-cert.pub"
        public_path.write_text(res_json["cert"])
        try:
            text = public_path.read_text()
            logging.warning("%s", text)
        except:
            pass

        private_path = ROOT_DIR / f"id_rsa_{username}"
        private_path.write_text(res_json["private"])
        try:
            text = private_path.read_text()
            logging.warning("%s", text)
        except:
            pass

        user = db.session.query(PlgridUserModel).filter_by(username=username).first()
        if not user:
            user = PlgridUserModel(username=username,
                                   auth_provider=AuthProvider.PLGRID.value,
                                   certificate="")

            db.session.add(user)
            db.session.commit()

        # exp = payload_dict["exp"]
        exp: int = int(request.headers.get('exp', ''))

        try:
            access_token, access_exp = encode_auth_token(user_id=user.id,
                                                         is_refresh=False,
                                                         exp_time=exp)
            refresh_token, refresh_exp = encode_auth_token(user_id=user.id,
                                                           is_refresh=True,
                                                           exp_time=exp)

            resp = yaptide_response(
                message='Successfully logged in',
                code=202,
                content={
                    'access_exp': int(access_exp.timestamp()*1000),
                    'refresh_exp': int(refresh_exp.timestamp()*1000),
                }
            )
            resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax', expires=access_exp)
            resp.set_cookie('refresh_token', refresh_token, httponly=True, samesite='Lax', expires=refresh_exp)
            return resp
        except Exception:  # skipcq: PYL-W0703
            return error_internal_response()

    @staticmethod
    def delete():
        """Method returning status of logging out"""
        resp = yaptide_response(message='User logged out', code=200)
        resp.delete_cookie('access_token')
        resp.delete_cookie('refresh_token')
        return resp
