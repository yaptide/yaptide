from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

class SlurmShieldhit(Resource):
    """Class responsible for jobs"""

    @staticmethod
    def post():
        """Method submiting job"""

    class _GetSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.Integer

    @staticmethod
    def get():
        """Method geting job's result"""
            
        schema = SlurmShieldhit._GetSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        



    @staticmethod
    def delete():
        """Method canceling job"""
