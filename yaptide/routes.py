from flask import request, json, make_response
from flask_api import status as api_status
from flask_restful import Resource

from werkzeug.datastructures import MultiDict
from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel

from yaptide.simulation_runner.shieldhit_runner import run_shieldhit, celery_app
from marshmallow import Schema, ValidationError
from marshmallow import fields as fld

from celery.result import AsyncResult

from typing import Union, Literal

import datetime

resources = []

############### Hello world ###############
# (this is used to test if app is running)


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


class ShieldhitDemoRun(Resource):
    """Class responsible for Shieldhit Demo running"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        jobs = fld.Integer(missing=1)
        energy = fld.Float(missing=150.0)
        nstat = fld.Integer(missing=1000)
        cyl_nr = fld.Integer(missing=1)
        cyl_nz = fld.Integer(missing=400)
        mesh_nx = fld.Integer(missing=1)
        mesh_ny = fld.Integer(missing=100)
        mesh_nz = fld.Integer(missing=300)

    @staticmethod
    def post() -> Union[dict[str, list[str]],
                        tuple[str, Literal[400]],
                        tuple[str, Literal[200]],
                        tuple[str, Literal[500]]]:
        """Method handling running shieldhit with server"""
        schema = ShieldhitDemoRun._Schema()
        args: MultiDict[str, str] = request.args
        errors: dict[str, list[str]] = schema.validate(args)
        if errors:
            return errors
        param_dict: dict = schema.load(args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return json.dumps({"msg": "Json Error"}), api_status.HTTP_400_BAD_REQUEST

        task = run_shieldhit.delay(param_dict=param_dict,
                                   raw_input_dict=json_data)

        return json.dumps({"task_id": task.id}), api_status.HTTP_202_ACCEPTED


class ShieldhitDemoStatus(Resource):
    """Class responsible for returning Shieldhit Demo status and result"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fld.String()

    @staticmethod
    def get():
        """Method returning task status and results"""
        schema = ShieldhitDemoStatus._Schema()
        args: MultiDict[str, str] = request.args

        errors: dict[str, list[str]] = schema.validate(args)
        if errors:
            return errors

        task_id = schema.load(args)["task_id"]
        task = AsyncResult(task_id, app=celery_app)

        if task.state == 'PENDING':
            response = {
                'state': task.state,
                'status': 'Pending...'
            }
        elif task.state != 'FAILURE':
            response = {
                'state': task.state,
                'status': task.info.get('status', '')
            }
            if 'result' in task.info:
                response['result'] = task.info['result']
        else:
            # something went wrong in the background job
            response = {
                'state': task.state,
                'status': str(task.info),  # this is the exception raised
            }
        return json.dumps(response)


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
            return {
                'status': 'ERROR',
                'message': 'Wrong data types provided'
            }, api_status.HTTP_400_BAD_REQUEST

        try:
            user = db.session.query(UserModel).filter_by(
                login_name=json_data.get('login_name')).first()
        except Exception:  # skipcq: PYL-W0703
            return {
                'status': 'ERROR',
                'message': 'Internal server error'
            }, api_status.HTTP_500_INTERNAL_SERVER_ERROR

        if not user:
            try:
                user = UserModel(
                    login_name=json_data.get('login_name')
                )
                user.set_password(json_data.get('password'))

                db.session.add(user)
                db.session.commit()

                return {
                    'status': 'SUCCESS',
                    'message': 'User created'
                }, api_status.HTTP_201_CREATED

            except Exception:  # skipcq: PYL-W0703
                return {
                    'status': 'ERROR',
                    'message': 'Internal server error'
                }, api_status.HTTP_500_INTERNAL_SERVER_ERROR
        else:
            return {
                'status': 'ERROR',
                'message': 'User existing'
            }, api_status.HTTP_202_ACCEPTED


_Cookie_lifetime = 1800  # move it later to some config file
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
            return {
                'status': 'ERROR',
                'message': 'Wrong data types provided'
            }, api_status.HTTP_400_BAD_REQUEST

        try:
            user = db.session.query(UserModel).filter_by(
                login_name=json_data.get('login_name')).first()
            if not user:
                return {
                    'status': 'ERROR',
                    'message': 'Unauthorized'
                }, api_status.HTTP_403_FORBIDDEN
            if not user.check_password(password=json_data.get('password')):
                return {
                    'status': 'ERROR',
                    'message': 'Unauthorized'
                }, api_status.HTTP_403_FORBIDDEN

            token = user.encode_auth_token(user_id=user.id)
            resp = make_response({
                'status': 'SUCCESS',
                'message': 'User logged in',
            }, api_status.HTTP_200_OK)
            resp.set_cookie('token', token, httponly=True, samesite='Lax',
                            expires=datetime.datetime.utcnow() + datetime.timedelta(seconds=_Cookie_lifetime))
            return resp
        except Exception:  # skipcq: PYL-W0703
            return {
                'status': 'ERROR',
                'message': 'Internal server error'
            }, api_status.HTTP_500_INTERNAL_SERVER_ERROR


class UserRefresh(Resource):
    """Class responsible for refreshing user"""

    @staticmethod
    def get():
        """Method refreshing token"""
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
        else:
            token = ''
        if token:
            resp = UserModel.decode_auth_token(token=token)
            if not isinstance(resp, str):
                user = db.session.query(UserModel).filter_by(id=resp).first()
                user.encode_auth_token(user_id=user.id)
                resp = make_response({
                    'status': 'SUCCESS',
                    'message': 'User logged in',
                }, api_status.HTTP_200_OK)
                resp.set_cookie('token', token, httponly=True, samesite='Lax',
                                expires=datetime.datetime.utcnow() + datetime.timedelta(seconds=_Cookie_lifetime))
                return resp
            return {
                'status': 'ERROR',
                'message': resp
            }, api_status.HTTP_401_UNAUTHORIZED
        return {
            'status': 'ERROR',
            'message': "Invalid token"
        }, api_status.HTTP_401_UNAUTHORIZED


class UserStatus(Resource):
    """Class responsible for returning user status"""

    @staticmethod
    def get():
        """Method returning user's status"""
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.split(" ")[1]
        else:
            token = ''
        if token:
            resp = UserModel.decode_auth_token(token=token)
            if not isinstance(resp, str):
                user = db.session.query(UserModel).filter_by(id=resp).first()
                return {
                    'status': 'SUCCESS',
                    'login_name': user.login_name
                }, api_status.HTTP_200_OK
            return {
                'status': 'ERROR',
                'message': resp
            }, api_status.HTTP_401_UNAUTHORIZED
        return {
            'status': 'ERROR',
            'message': "Invalid token"
        }, api_status.HTTP_401_UNAUTHORIZED


def initialize_routes(api):
    api.add_resource(HelloWorld, "/")

    api.add_resource(ShieldhitDemoRun, "/sh/run")
    api.add_resource(ShieldhitDemoStatus, "/sh/status")

    api.add_resource(UserRegister, "/auth/register")
    api.add_resource(UserLogIn, "/auth/login")
    api.add_resource(UserRefresh, "/auth/refresh")
    api.add_resource(UserStatus, "/auth/status")
