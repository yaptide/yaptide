import logging

from flask import request
from flask_restful import Resource
from marshmallow import Schema, ValidationError, fields

from yaptide.persistence.db_methods import (add_object_to_db,
                                            fetch_yaptide_user_by_username)
from yaptide.persistence.models import YaptideUserModel
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import (  # skipcq: FLK-E101
    error_internal_response, error_validation_response, yaptide_response)
from yaptide.routes.utils.tokens import encode_auth_token


class AuthRegister(Resource):
    """Class responsible for user registration"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        username = fields.String()
        password = fields.String()

    @staticmethod
    def put():
        """Method returning status of registration"""
        try:
            json_data: dict = AuthRegister.APIParametersSchema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        user = fetch_yaptide_user_by_username(username=json_data.get('username'))

        if not user:
            try:
                user = YaptideUserModel(username=json_data.get('username'))
                user.set_password(json_data.get('password'))

                add_object_to_db(user)

                return yaptide_response(message='User created', code=201)

            except Exception as e:  # skipcq: PYL-W0703
                logging.error("%s", e)
                return error_internal_response()
        else:
            return yaptide_response(message='User existing', code=403)


class AuthLogIn(Resource):
    """Class responsible for user log in"""

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        required_keys = {"username", "password"}

        if required_keys != required_keys.intersection(set(payload_dict.keys())):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        try:
            user: YaptideUserModel = fetch_yaptide_user_by_username(username=payload_dict['username'])
            if not user:
                return yaptide_response(message='Invalid login or password', code=401)

            if not user.check_password(password=payload_dict['password']):
                return yaptide_response(message='Invalid login or password', code=401)

            access_token, access_exp = encode_auth_token(user_id=user.id, is_refresh=False)
            refresh_token, refresh_exp = encode_auth_token(user_id=user.id, is_refresh=True)

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
        except Exception as e:  # skipcq: PYL-W0703
            logging.error("%s", e)
            return error_internal_response()


class AuthRefresh(Resource):
    """Class responsible for refreshing user"""

    @staticmethod
    @requires_auth(is_refresh=True)
    def get(user: YaptideUserModel):
        """Method refreshing token"""
        access_token, access_exp = encode_auth_token(user_id=user.id, is_refresh=False)
        resp = yaptide_response(
            message='User refreshed',
            code=200,
            content={'access_exp': int(access_exp.timestamp()*1000)}
        )
        resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax', expires=access_exp)
        return resp


class AuthStatus(Resource):
    """Class responsible for returning user status"""

    @staticmethod
    @requires_auth()
    def get(user: YaptideUserModel):
        """Method returning user's status"""
        return yaptide_response(
            message='User status',
            code=200,
            content={'username': user.username}
        )


class AuthLogOut(Resource):
    """Class responsible for user log out"""

    @staticmethod
    def delete():
        """Method logging the user out"""
        resp = yaptide_response(message='User logged out', code=200)
        resp.delete_cookie('access_token')
        resp.delete_cookie('refresh_token')
        return resp
