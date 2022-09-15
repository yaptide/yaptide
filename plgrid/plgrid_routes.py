from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

from plgrid.rimrock_methods import submit_job, get_job, delete_job
from plgrid.plgdata_methods import fetch_bdo_files


class RimrockJobs(Resource):
    """Class responsible for jobs"""

    @staticmethod
    def post():
        """Method submiting job"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return error_validation_response()
        json_data['grid_proxy'] = request.headers.get("PROXY")
        result, status_code = submit_job(json_data=json_data)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(missing="None")

    @staticmethod
    def get():
        """Method geting job's result"""
        schema = RimrockJobs._ParamsSchema()
        json_data = {
            "grid_proxy": request.headers.get("PROXY")
        }
        params_dict: dict = schema.load(request.args)
        if params_dict.get("job_id") != "None":
            json_data["job_id"] = params_dict.get("job_id")
        result, status_code = get_job(json_data=json_data)
        
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    @staticmethod
    def delete():
        """Method canceling job"""
        schema = RimrockJobs._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
            "grid_proxy": request.headers.get("PROXY"),
            "job_id": params_dict.get("job_id")
        }
        result, status_code = delete_job(json_data=json_data)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )


class PlgData(Resource):
    """Class responsible for files management"""

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()
        plguserlogin = fields.String()

    @staticmethod
    def get():
        """Method geting job's result"""
        schema = PlgData._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
            "grid_proxy": request.headers.get("PROXY"),
            "job_id": params_dict.get("job_id"),
            "plguserlogin": params_dict.get("plguserlogin")
        }
        result, status_code = fetch_bdo_files(json_data=json_data)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )
