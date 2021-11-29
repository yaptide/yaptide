from flask import request, json, make_response
from flask_api import status as api_status
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel
from yaptide.utils import encode_auth_token, decode_auth_token

from yaptide.celery.tasks import run_simulation, simulation_task_status

from marshmallow import Schema, ValidationError
from marshmallow import fields as fld

from typing import Union, Literal
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Unauthorized, Forbidden

from functools import wraps

resources = []


def requires_auth(isRefresh: bool):
    """Decorator for auth requirements"""
    def decorator(f):
        """Determines if the access or refresh token is valid"""
        @wraps(f)
        def wrapper(*args, **kwargs):
            token: str = request.cookies.get(
                'refresh_token' if isRefresh else 'access_token')
            if not token:
                raise Unauthorized(description="No token provided")
            resp: Union[int, str] = decode_auth_token(
                token=token, isRefresh=isRefresh)
            if isinstance(resp, int):
                user = db.session.query(UserModel).filter_by(id=resp).first()
                if user:
                    return f(user, *args, **kwargs)
                raise Forbidden(description="User not found")
            if isRefresh:
                raise Forbidden(description="Log in again")
            raise Forbidden(description="Refresh access token")
        return wrapper
    return decorator


############### Hello world ###############
# (this is used to test if app is running)


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


class SimulationRun(Resource):
    """Class responsible for Shieldhit Demo running"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        jobs = fld.Integer(missing=1)

    @staticmethod
    # @requires_auth(isRefresh=False)
    # def post(user: UserModel) -> Union[dict[str, list[str]],
    def post() -> Union[dict[str, list[str]],
                                       tuple[str, Literal[400]],
                                       tuple[str, Literal[200]],
                                       tuple[str, Literal[500]]]:
        """Method handling running shieldhit with server"""
        schema = SimulationRun._Schema()
        args: MultiDict[str, str] = request.args
        errors: dict[str, list[str]] = schema.validate(args)
        if errors:
            return make_response(errors, api_status.HTTP_400_BAD_REQUEST)
        param_dict: dict = schema.load(args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return make_response({
                'status': 'ERROR',
                'message': 'JSON not provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        task = run_simulation.delay(
            param_dict=param_dict, raw_input_dict=json_data)
        return make_response({
            'status': 'ACCEPTED',
            'message': {
                'task_id': task.id
            }
        }, api_status.HTTP_202_ACCEPTED)


class SimulationStatus(Resource):
    """Class responsible for returning Shieldhit Demo status and result"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fld.String()

    @staticmethod
    # @requires_auth(isRefresh=False)
    # def get(user: UserModel):
    def get():
        """Method returning task status and results"""
        try:
            json_data: dict = SimulationStatus._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        result = simulation_task_status(task_id=json_data.get('task_id'))

        if result.get('status') == 'OK':
            return make_response(result.get('message'), api_status.HTTP_200_OK)
        
        return make_response(result.get('message'), api_status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserRegister(Resource):
    """Class responsible for user registration"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        login_name = fld.String()
        password = fld.String()

    @staticmethod
    def put():
        """Method returning status of registration"""
        try:
            json_data: dict = UserRegister._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data types provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        try:
            user = db.session.query(UserModel).filter_by(
                login_name=json_data.get('login_name')).first()
        except Exception:  # skipcq: PYL-W0703
            return make_response({
                'status': 'ERROR',
                'message': 'Internal server error'
            }, api_status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not user:
            try:
                user = UserModel(
                    login_name=json_data.get('login_name')
                )
                user.set_password(json_data.get('password'))

                db.session.add(user)
                db.session.commit()

                return make_response({
                    'status': 'SUCCESS',
                    'message': 'User created'
                }, api_status.HTTP_201_CREATED)

            except Exception:  # skipcq: PYL-W0703
                return make_response({
                    'status': 'ERROR',
                    'message': 'Internal server error'
                }, api_status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return make_response({
                'status': 'ERROR',
                'message': 'User existing'
            }, api_status.HTTP_403_FORBIDDEN)


class UserLogIn(Resource):
    """Class responsible for user log in"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        login_name = fld.String()
        password = fld.String()

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        try:
            json_data: dict = UserLogIn._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        try:
            user = db.session.query(UserModel).filter_by(
                login_name=json_data.get('login_name')).first()
            if not user:
                return make_response({
                    'status': 'ERROR',
                    'message': 'Invalid login or password'
                }, api_status.HTTP_401_UNAUTHORIZED)
            if not user.check_password(password=json_data.get('password')):
                return make_response({
                    'status': 'ERROR',
                    'message': 'Invalid login or password'
                }, api_status.HTTP_401_UNAUTHORIZED)

            access_token, access_exp = encode_auth_token(
                user_id=user.id, isRefresh=False)
            refresh_token, refresh_exp = encode_auth_token(
                user_id=user.id, isRefresh=True)

            resp = make_response({
                'status': 'SUCCESS',
                'message': {
                    'access_exp': int(access_exp.timestamp()*1000),
                    'refresh_exp': int(refresh_exp.timestamp()*1000)
                },
            }, api_status.HTTP_202_ACCEPTED)
            resp.set_cookie('access_token', access_token, httponly=True, samesite='Lax',
                            expires=access_exp)
            resp.set_cookie('refresh_token', refresh_token, httponly=True, samesite='Lax',
                            expires=refresh_exp)
            return resp
        except Exception:  # skipcq: PYL-W0703
            return make_response({
                'status': 'ERROR',
                'message': 'Internal server error'
            }, api_status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserRefresh(Resource):
    """Class responsible for refreshing user"""

    @staticmethod
    @requires_auth(isRefresh=True)
    def get(user: UserModel):
        """Method refreshing token"""
        access_token, access_exp = encode_auth_token(
            user_id=user.id, isRefresh=False)
        resp = make_response({
            'status': 'SUCCESS',
            'message': 'User logged in',
        }, api_status.HTTP_200_OK)
        resp.set_cookie('token', access_token, httponly=True, samesite='Lax',
                        expires=access_exp)
        return resp


class UserStatus(Resource):
    """Class responsible for returning user status"""

    @staticmethod
    @requires_auth(isRefresh=False)
    def get(user: UserModel):
        """Method returning user's status"""
        resp = make_response({
            'status': 'SUCCESS',
            'login_name': user.login_name
        }, api_status.HTTP_200_OK)
        return resp


class UserLogOut(Resource):
    """Class responsible for user log out"""

    @staticmethod
    def delete():
        """Method logging the user out"""
        resp = make_response({
            'status': 'SUCCESS'
        }, api_status.HTTP_200_OK)
        resp.delete_cookie('access_token')
        resp.delete_cookie('refresh_token')
        return resp


def initialize_routes(api):
    api.add_resource(HelloWorld, "/")

    api.add_resource(SimulationRun, "/sh/run")
    api.add_resource(SimulationStatus, "/sh/status")

    api.add_resource(UserRegister, "/auth/register")
    api.add_resource(UserLogIn, "/auth/login")
    api.add_resource(UserRefresh, "/auth/refresh")
    api.add_resource(UserStatus, "/auth/status")
    api.add_resource(UserLogOut, "/auth/logout")
