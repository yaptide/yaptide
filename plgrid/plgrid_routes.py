from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from plgrid.rimrock_methods import submit_job, get_job, delete_job
from plgrid.plgdata_methods import fetch_bdo_files


class RimrockJobs(Resource):
    """Class responsible for jobs"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method submiting job"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return error_validation_response()
        result, status_code = submit_job(json_data=json_data)

        if "job_id" in result:
            simulation = SimulationModel(
                job_id=result["job_id"], user_id=user.id, platform=SimulationModel.Platform.RIMROCK.value)
            db.session.add(simulation)
            db.session.commit()

        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(load_default="None")

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method geting job's result"""
        schema = RimrockJobs._ParamsSchema()
        json_data = {}
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
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling job"""
        schema = RimrockJobs._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
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

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method geting job's result"""
        schema = PlgData._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)
        json_data = {
            "job_id": params_dict.get("job_id")
        }
        result, status_code = fetch_bdo_files(json_data=json_data)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )
