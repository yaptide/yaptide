from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.batch.batch_methods import submit_job, get_job, delete_job


class JobsBatch(Resource):
    """Class responsible for jobs via direct slurm connection"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with batch"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in json_data:
            return error_validation_response()

        sim_type = SimulationModel.SimType.SHIELDHIT.value if "sim_type" not in json_data or\
            json_data["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value else\
            SimulationModel.SimType.DUMMY.value

        input_type = SimulationModel.InputType.YAPTIDE_PROJECT.value if\
            "metadata" in json_data["sim_data"] else\
            SimulationModel.InputType.INPUT_FILES.value

        result, status_code = submit_job(json_data=json_data)

        if "job_id" in result:
            if "title" in json_data:
                simulation = SimulationModel(
                    job_id=result["job_id"],
                    user_id=user.id,
                    title=json_data['title'],
                    platform=SimulationModel.Platform.BATCH.value,
                    sim_type=sim_type,
                    input_type=input_type
                    )
            else:
                simulation = SimulationModel(
                    job_id=result["job_id"],
                    user_id=user.id,
                    platform=SimulationModel.Platform.BATCH.value,
                    sim_type=sim_type,
                    input_type=input_type
                    )
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
        schema = JobsBatch._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=params_dict["job_id"], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation: SimulationModel = db.session.query(SimulationModel).\
            filter_by(job_id=params_dict["job_id"]).first()

        json_data = {
            "job_id": params_dict["job_id"],
            "start_time_for_dummy": simulation.start_time,
            "end_time_for_dummy": simulation.end_time
        }

        result, status_code = get_job(json_data=json_data)

        if "end_time" in result and simulation.end_time is None:
            simulation.end_time = result['end_time']
            db.session.commit()

        result.pop("end_time", None)

        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling job"""
        schema = JobsBatch._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=params_dict["job_id"], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        json_data = {
            "job_id": params_dict["job_id"]
        }
        result, status_code = delete_job(json_data=json_data)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )


def check_if_job_is_owned(job_id: str, user: UserModel) -> tuple[bool, str]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

    if not simulation:
        return False, 'Task with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Task with provided ID does not belong to the user', 403
