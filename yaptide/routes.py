from flask import request, json, make_response
from flask_api import status as api_status
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel
from yaptide.utils import encode_auth_token, decode_auth_token

from yaptide.celery.tasks import run_simulation, simulation_task_status, get_input_files, cancel_simulation

from marshmallow import Schema, ValidationError
from marshmallow import fields as fld

from typing import Union, Literal
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Unauthorized, Forbidden

from functools import wraps

resources = []


def requires_auth(is_refresh: bool):
    """Decorator for auth requirements"""
    def decorator(f):
        """Determines if the access or refresh token is valid"""
        @wraps(f)
        def wrapper(*args, **kwargs):
            token: str = request.cookies.get('refresh_token' if is_refresh else 'access_token')
            if not token:
                raise Unauthorized(description="No token provided")
            resp: Union[int, str] = decode_auth_token(token=token, is_refresh=is_refresh)
            if isinstance(resp, int):
                user = db.session.query(UserModel).filter_by(id=resp).first()
                if user:
                    return f(user, *args, **kwargs)
                raise Forbidden(description="User not found")
            if is_refresh:
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
        sim_type = fld.String(missing="shieldhit")

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel) -> Union[dict[str, list[str]],
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

        task = run_simulation.delay(param_dict=param_dict, raw_input_dict=json_data)

        simulation = SimulationModel(task_id=task.id, user_id=user.id)

        db.session.add(simulation)
        db.session.commit()

        return make_response({
            'status': 'ACCEPTED',
            'message': {
                'task_id': task.id
            }
        }, api_status.HTTP_202_ACCEPTED)


def check_if_task_is_owned(task_id: str, user: UserModel) -> tuple[bool, dict]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(task_id=task_id).first()

    if simulation.user_id == user.id:
        return True, {}
    return False, {
        'status': 'ERROR',
        'message': 'Task with provided ID does not belong to the user',
    }


class SimulationStatus(Resource):
    """Class responsible for returning Shieldhit Demo status and result"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fld.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method returning task status and results"""
        try:
            json_data: dict = SimulationStatus._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return make_response(error_message, api_status.HTTP_403_FORBIDDEN)

        task = simulation_task_status.delay(task_id=json_data.get('task_id'))
        result = task.wait(timeout=None, interval=0.5)

        if result.get('status') == 'OK':
            if result.get('message').get('result'):
                db.session.query(SimulationModel).filter_by(
                    task_id=json_data.get('task_id')).delete()
                db.session.commit()
            return make_response(result.get('message'), api_status.HTTP_200_OK)
        return make_response(result.get('message'), api_status.HTTP_500_INTERNAL_SERVER_ERROR)


class SimulationInputs(Resource):
    """Class responsible for returning converted simulation input files"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fld.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method returning simulation input files"""
        try:
            json_data: dict = SimulationInputs._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return make_response(error_message, api_status.HTTP_403_FORBIDDEN)

        task = get_input_files.delay(task_id=json_data.get('task_id'))
        result = task.wait(timeout=None, interval=0.5)

        return make_response(result.get('message'), api_status.HTTP_200_OK)


class SimulationCancel(Resource):
    """Class responsible for canceling simulation"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fld.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        try:
            json_data: dict = SimulationCancel._Schema().load(request.get_json(force=True))
        except ValidationError:
            return make_response({
                'status': 'ERROR',
                'message': 'Wrong data provided'
            }, api_status.HTTP_400_BAD_REQUEST)

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return make_response(error_message, api_status.HTTP_403_FORBIDDEN)

        task = cancel_simulation.delay(task_id=json_data.get('task_id'))
        result = task.wait(timeout=None, interval=0.5)

        if result['status'] != 'ERROR':
            db.session.query(SimulationModel).filter_by(task_id=json_data.get('task_id')).delete()
            db.session.commit()

        return make_response(result, api_status.HTTP_200_OK)


class UserSimulations(Resource):
    """Class responsible for returning ids of user's task which are running simulations"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning ids"""
        simulations = db.session.query(SimulationModel).filter_by(user_id=user.id).all()

        if len(simulations) > 0:
            result = {
                'message': {
                    'tasks_ids': [],
                },
                'status': 'OK'
            }
            for simulation in simulations:
                result['message']['tasks_ids'].append(simulation.task_id)
        else:
            result = {
                'message': 'There are no simulations'
            }
        return make_response(result, api_status.HTTP_200_OK)


class AuthRegister(Resource):
    """Class responsible for user registration"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        login_name = fld.String()
        password = fld.String()

    @staticmethod
    def put():
        """Method returning status of registration"""
        try:
            json_data: dict = AuthRegister._Schema().load(request.get_json(force=True))
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


class AuthLogIn(Resource):
    """Class responsible for user log in"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        login_name = fld.String()
        password = fld.String()

    @staticmethod
    def post():
        """Method returning status of logging in (and token if it was successful)"""
        try:
            json_data: dict = AuthLogIn._Schema().load(request.get_json(force=True))
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

            access_token, access_exp = encode_auth_token(user_id=user.id, is_refresh=False)
            refresh_token, refresh_exp = encode_auth_token(user_id=user.id, is_refresh=True)

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


class AuthRefresh(Resource):
    """Class responsible for refreshing user"""

    @staticmethod
    @requires_auth(is_refresh=True)
    def get(user: UserModel):
        """Method refreshing token"""
        access_token, access_exp = encode_auth_token(user_id=user.id, is_refresh=False)
        resp = make_response({
            'status': 'SUCCESS',
            'message': 'User logged in',
        }, api_status.HTTP_200_OK)
        resp.set_cookie('token', access_token, httponly=True, samesite='Lax', expires=access_exp)
        return resp


class AuthStatus(Resource):
    """Class responsible for returning user status"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning user's status"""
        resp = make_response({
            'status': 'SUCCESS',
            'login_name': user.login_name
        }, api_status.HTTP_200_OK)
        return resp


class AuthLogOut(Resource):
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
    api.add_resource(SimulationInputs, "/sh/inputs")
    api.add_resource(SimulationCancel, "/sh/cancel")

    api.add_resource(UserSimulations, "/user/simulations")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")
