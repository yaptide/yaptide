from flask import request, json, jsonify
from flask_api import status as api_status
from flask_restful import Resource, reqparse, fields, marshal_with, abort
from warnings import resetwarnings

from werkzeug.datastructures import MultiDict
from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel

from yaptide.simulation_runner.shieldhit_runner import run_shieldhit, celery_app
from marshmallow import Schema
from marshmallow import fields as fld

from celery.result import AsyncResult

from typing import Union, Literal

resources = []

############### Hello world ###############
# (this is used to test if app is running)


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


############################################


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


class UserLogIn(Resource):
    """Class responsible for user log in"""

    @staticmethod
    def post():
        """Method returning token if logging in ends successfully"""


############### Example user ###############
# (this is an example route, demonstration pourpose only)
user_args = reqparse.RequestParser()
user_args.add_argument(
    "name", type=str, help="Example user name is required and must be a string.", required=True)

user_modify_args = reqparse.RequestParser()
user_modify_args.add_argument(
    "name", type=str, help="Example user name is required and must be a string.")

user_fields = {
    'id': fields.Integer,
    'name': fields.String,
}


class UserResource(Resource):
    @marshal_with(user_fields)
    def get(self, user_id):
        user = UserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        return user

    @marshal_with(user_fields)
    def put(self):
        args = user_args.parse_args()
        user = UserModel(name=args.name)
        db.session.add(user)
        db.session.commit()
        if not user:
            abort(500, "Something went wrong.")
        return user, 201

    @marshal_with(user_fields)
    def delete(self, user_id):
        user = UserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        db.session.delete(user)
        db.session.commit()
        return user, 202

    @marshal_with(user_fields)
    def patch(self, user_id):
        args = user_modify_args.parse_args()
        user = UserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        for key, value in args.items():
            if value:
                setattr(user, key, value)
        db.session.commit()
        print(user)
        return user, 202

############################################


def initialize_routes(api):
    api.add_resource(UserResource,
                     "/user/<int:user_id>", "/user")
    api.add_resource(HelloWorld, "/")
    api.add_resource(ShieldhitDemoRun, "/sh/run")
    api.add_resource(ShieldhitDemoStatus, "/sh/status")
