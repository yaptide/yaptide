from flask import request, json
from flask_api import status as api_status
from flask_restful import Resource, reqparse, fields, marshal_with, abort
from warnings import resetwarnings
from yaptide.persistence.database import db
from yaptide.persistence.models import ExampleUserModel
from yaptide.simulation_runner.shieldhit_runner import run_shieldhit
from marshmallow import Schema
from marshmallow import fields as fld

resources = []

############### Hello world ###############
# (this is used to test if app is running)


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


############################################

class SHSchema(Schema):
    """Class specifies API parameters"""

    jobs = fld.Integer(missing=1)
    energy = fld.Float(missing=150.0)
    nstat = fld.Integer(missing=1000)
    cyl_nr = fld.Integer(missing=1)
    cyl_nz = fld.Integer(missing=400)
    mesh_nx = fld.Integer(missing=1)
    mesh_ny = fld.Integer(missing=100)
    mesh_nz = fld.Integer(missing=300)


class ShieldhitDemo(Resource):
    """Class responsible for Shieldhit Demo running"""

    @staticmethod
    def post():
        """Method handling running shieldhit with server"""
        shschema = SHSchema()
        args = request.args
        errors = shschema.validate(args)
        if errors:
            return errors
        param_dict: dict = shschema.load(args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return json.dumps({"msg": "Json Error"}), api_status.HTTP_400_BAD_REQUEST

        simulation_result = run_shieldhit(param_dict=param_dict,
                                          raw_input_dict=json_data)

        if simulation_result:
            return json.dumps(simulation_result), api_status.HTTP_200_OK
        return json.dumps({"msg": "Sim Error"}), api_status.HTTP_500_INTERNAL_SERVER_ERROR


############### Example user ###############
# (this is an example route, demonstration pourpose only)
example_user_args = reqparse.RequestParser()
example_user_args.add_argument(
    "name", type=str, help="Example user name is required and must be a string.", required=True)

example_user_modify_args = reqparse.RequestParser()
example_user_modify_args.add_argument(
    "name", type=str, help="Example user name is required and must be a string.")

example_user_fields = {
    'id': fields.Integer,
    'name': fields.String,
}


class ExampleUserResource(Resource):
    @marshal_with(example_user_fields)
    def get(self, user_id):
        user = ExampleUserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        return user

    @marshal_with(example_user_fields)
    def put(self):
        args = example_user_args.parse_args()
        user = ExampleUserModel(name=args.name)
        db.session.add(user)
        db.session.commit()
        if not user:
            abort(500, "Something went wrong.")
        return user, 201

    @marshal_with(example_user_fields)
    def delete(self, user_id):
        user = ExampleUserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        db.session.delete(user)
        db.session.commit()
        return user, 202

    @marshal_with(example_user_fields)
    def patch(self, user_id):
        args = example_user_modify_args.parse_args()
        user = ExampleUserModel.query.get_or_404(
            user_id, description=f"User with id {user_id} not found.")
        for key, value in args.items():
            if value:
                setattr(user, key, value)
        db.session.commit()
        print(user)
        return user, 202

############################################


def initialize_routes(api):
    api.add_resource(ExampleUserResource,
                     "/example_user/<int:user_id>", "/example_user")
    api.add_resource(HelloWorld, "/")
    api.add_resource(ShieldhitDemo, "/sh/demo")
