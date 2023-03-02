from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from datetime import datetime

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

from yaptide.celery.tasks import (run_simulation, convert_input_files, simulation_task_status,
                                  get_input_files, cancel_simulation)


class JobsDirect(Resource):
    """Class responsible for simulations run directly with celery"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with server"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in json_data:
            return error_validation_response()

        job = run_simulation.delay(param_dict={
            "jobs": json_data["jobs"] if "jobs" in json_data else -1,
            "sim_type": json_data["sim_type"] if "sim_type" in json_data else "shieldhit"
        }, raw_input_dict=json_data["sim_data"])

        if json_data.get('title'):
            simulation = SimulationModel(
                job_id=job.id, user_id=user.id, title=json_data['title'],
                platform=SimulationModel.Platform.DIRECT.value)
        else:
            simulation = SimulationModel(
                job_id=job.id, user_id=user.id, platform=SimulationModel.Platform.DIRECT.value)

        db.session.add(simulation)
        db.session.commit()

        return yaptide_response(
            message="Task started",
            code=202,
            content={'job_id': job.id}
        )

    class _Schema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning job status and results"""
        schema = JobsDirect._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_task_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = simulation_task_status.delay(job_id=job_id)
        result: dict = job.wait()
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        if "end_time" in result and simulation.end_time is None:
            simulation.end_time = datetime.strptime(result['end_time'], '%Y-%m-%dT%H:%M:%S.%f')
            db.session.commit()

        result.pop("end_time", None)

        return yaptide_response(
            message=f"Job state: {result['job_state']}",
            code=200,
            content=result
        )

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        try:
            json_data: dict = JobsDirect._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message, res_code = check_if_task_is_owned(job_id=json_data.get('job_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = cancel_simulation.delay(job_id=json_data.get('job_id'))
        result: dict = job.wait()

        if result:
            db.session.query(SimulationModel).filter_by(job_id=json_data.get('job_id')).delete()
            db.session.commit()

        return error_internal_response()


class ConvertInputFiles(Resource):
    """Class responsible for returning input files converted from front JSON"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        sim_type = fields.String(load_default="shieldhit")

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):  # skipcq: PYL-W0613
        """Method handling input files convertion"""
        schema = ConvertInputFiles._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        job = convert_input_files.delay(param_dict=param_dict, raw_input_dict=json_data)
        result: dict = job.wait()

        return yaptide_response(
            message="Converted Input Files",
            code=200,
            content=result
        )


def check_if_task_is_owned(job_id: str, user: UserModel) -> tuple[bool, str]:
    """Function checking if provided job is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

    if not simulation:
        return False, 'Task with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Task with provided ID does not belong to the user', 403


class SimulationInputs(Resource):
    """Class responsible for returning converted simulation input files"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning simulation input files"""
        schema = SimulationInputs._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)
        job_id = param_dict['job_id']

        is_owned, error_message, res_code = check_if_task_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = get_input_files.delay(job_id=job_id)
        result: dict = job.wait()

        return yaptide_response(
            message=result['info'],
            code=200,
            content=result
        )
