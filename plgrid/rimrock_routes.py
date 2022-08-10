from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from yaptide.routes.utils.response_templates import yaptide_response

from plgrid.rimrock_methods import submit_job, get_job, delete_job


class RimrockJobs(Resource):
    """Class responsible for jobs"""

    @staticmethod
    def post():
        """Method submiting job"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)
        json_data["grid_proxy"] = request.headers.get("PROXY")
        result = submit_job(json_data=json_data)
        return yaptide_response(
            message="Nth",
            code=201,
            content=result
        )

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    def get():
        """Method geting job's result"""
        schema = RimrockJobs._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
            "grid_proxy": request.headers.get("PROXY"),
            "job_id": params_dict.get("job_id")
        }
        result = get_job(json_data=json_data)
        return yaptide_response(
            message="TODO",
            code=200,
            content=result
        )

    @staticmethod
    def delete():
        """Method canceling job"""
        schema = RimrockJobs._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
            "grid_proxy": request.headers.get("PROXY"),
            "job_id": params_dict.get("job_id")
        }
        result = delete_job(json_data=json_data)
        return yaptide_response(
            message="TODO",
            code=204,
            content=result
        )

