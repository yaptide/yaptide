from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from yaptide.persistence.database import db
from yaptide.persistence.models import YaptideUserModel

from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response


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

        try:
            user = db.session.query(YaptideUserModel).filter_by(
                username=json_data.get('username')).first()
        except Exception:  # skipcq: PYL-W0703
            return error_internal_response()

        if not user:
            try:
                user = YaptideUserModel(
                    username=json_data.get('username')
                )
                user.set_password(json_data.get('password'))

                db.session.add(user)
                db.session.commit()

                return yaptide_response(message='User created', code=201)

            except Exception:  # skipcq: PYL-W0703
                return error_internal_response()
        else:
            return yaptide_response(message='User existing', code=403)


class AuthLogIn(Resource):
    """Class responsible for user log in"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        username = fields.String()
        password = fields.String()

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        try:
            json_data: dict = AuthLogIn.APIParametersSchema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        try:
            user = db.session.query(YaptideUserModel).filter_by(username=json_data.get('username')).first()
            if not user:
                return yaptide_response(message='Invalid login or password', code=401)

            if not user.check_password(password=json_data.get('password')):
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
        except Exception:  # skipcq: PYL-W0703
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
    @requires_auth(is_refresh=False)
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
