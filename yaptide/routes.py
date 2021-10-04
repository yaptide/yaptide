from warnings import resetwarnings
from yaptide.persistence.database import db
from yaptide.persistence.models import ExampleUserModel
from flask_restful import Resource, reqparse, fields, marshal_with, abort

resources = []

############### Hello world ###############
# (this is used to test if app is running)


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


############################################


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
