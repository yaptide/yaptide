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
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in payload_dict:
            return error_validation_response()

        sim_type = (SimulationModel.SimType.SHIELDHIT.value
                    if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value
                    else SimulationModel.SimType.DUMMY.value)

        input_type = (SimulationModel.InputType.YAPTIDE_PROJECT.value
                      if "metadata" in payload_dict["sim_data"]
                      else SimulationModel.InputType.INPUT_FILES.value)

        job = run_simulation.delay(payload_dict={
            "ntasks": payload_dict["ntasks"] if "ntasks" in payload_dict else -1,
            "sim_type": sim_type.lower(),
            "sim_data": payload_dict["sim_data"]
        })

        simulation = SimulationModel(
            job_id=job.id,
            user_id=user.id,
            platform=SimulationModel.Platform.DIRECT.value,
            sim_type=sim_type,
            input_type=input_type
        )
        if "title" in payload_dict:
            simulation.set_title(payload_dict["title"])

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
            payload_dict: dict = JobsDirect._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message, res_code = check_if_task_is_owned(job_id=payload_dict.get('job_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = cancel_simulation.delay(job_id=payload_dict.get('job_id'))
        result: dict = job.wait()

        if result:
            db.session.query(SimulationModel).filter_by(job_id=payload_dict.get('job_id')).delete()
            db.session.commit()

        return error_internal_response()


class ConvertInputFiles(Resource):
    """Class responsible for returning input files converted from front JSON"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(_: UserModel):
        """Method handling input files convertion"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        sim_type = (SimulationModel.SimType.SHIELDHIT.value
                    if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value
                    else SimulationModel.SimType.DUMMY.value)

        # Rework in later PRs to match pattern from jobs endpoint
        job = convert_input_files.delay(payload_dict={
            "sim_type": sim_type.lower(),
            "sim_data": payload_dict
        })
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
