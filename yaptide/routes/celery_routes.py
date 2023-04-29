from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from datetime import datetime
import uuid

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel, ResultModel, TaskModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

from yaptide.celery.tasks import (
    run_simulation,
    convert_input_files,
    get_input_files,
    cancel_simulation
)
from yaptide.celery.utils.utils import get_job_status_as_dict, get_job_results


class JobsDirect(Resource):
    """Class responsible for simulations run directly with celery"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Submit simulation job to celery"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in payload_dict:
            return error_validation_response()

        # TODO handle better lower and upper case
        sim_type = (SimulationModel.SimType.SHIELDHIT.value
                    if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value
                    else SimulationModel.SimType.DUMMY.value)

        input_type = (SimulationModel.InputType.YAPTIDE_PROJECT.value
                      if "metadata" in payload_dict["sim_data"]
                      else SimulationModel.InputType.INPUT_FILES.value)

        # submit the job to the Celery queue
        update_key = str(uuid.uuid4())
        job = run_simulation.delay(payload_dict=payload_dict)

        # create a new simulation in the database, not waiting for the job to finish
        simulation = SimulationModel(
            job_id=job.id,
            user_id=user.id,
            platform=SimulationModel.Platform.DIRECT.value,
            sim_type=sim_type,
            title = payload_dict.get("title", ''),
            input_type=input_type
        )
        db.session.add(simulation)
        db.session.commit()

        return yaptide_response(
            message="Task started",
            code=202,
            content={'job_id': job.id}
        )

    class _Schema(Schema):
        """Class specifies API parameters for GET and DELETE request"""
        job_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning job status and results"""
        # validate request parameters and handle errors
        schema = JobsDirect._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        # get job_id from request parameters and check if user owns this job
        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        # get job status from Celery, extracting status from job.info
        # this dict will be returned to the user as a response to GET request
        result: dict = get_job_status_as_dict(job_id=job_id)

        # find appropriate simulation in the database
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        # if simulation is not found, return error
        if "end_time" in result and simulation.end_time is None:
            simulation.end_time = datetime.strptime(result['end_time'], '%Y-%m-%dT%H:%M:%S.%f')
            db.session.commit()

        # remove end_time from result, as it is not needed in response
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

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=payload_dict.get('job_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = cancel_simulation.delay(job_id=payload_dict.get('job_id'))
        result: dict = job.wait()

        if result:
            db.session.query(SimulationModel).filter_by(job_id=payload_dict.get('job_id')).delete()
            db.session.commit()

        return error_internal_response()


class ResultsDirect(Resource):
    """Class responsible for returning simulation results"""

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
        is_owned, error_message, res_code = check_if_job_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        results: list[ResultModel] = db.session.query(ResultModel).filter_by(job_id=job_id).all()
        if len(results) > 0:
            # TODO: return results from database
            pass
        result: dict = get_job_results(job_id=job_id)
        if "result" not in result:
            return yaptide_response(
                message="Results are unavailable",
                code=200,
                content=result
            )

        if "end_time" in result and simulation.end_time is None:
            simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()
            simulation.end_time = datetime.strptime(result['end_time'], '%Y-%m-%dT%H:%M:%S.%f')
            db.session.commit()

        result.pop("end_time", None)

        return yaptide_response(
            message=f"Results for job: {job_id}",
            code=200,
            content=result
        )


class TaskDirect(Resource):
    """Class responsible for updating tasks"""

    @staticmethod
    def post():
        """
        Method updating task state
        Structure required by this method to work properly:
        {
            "simulation_id": <string>,
            "task_id": <string>,
            "update_key": <string>,
            "update_dict": <dict>
        }
        simulation_id and task_id self explanatory
        """
        payload_dict: dict = request.get_json(force=True)
        required_keys = set(["simulation_id", "task_id", "auth_key", "update_dict"])
        if not required_keys.intersection(set(payload_dict.keys())):
            return yaptide_response(message="Incomplete JSON data", code=400)
        
        # TODO: make use of auth_key or any other auth method

        simulation: SimulationModel = db.session.query.filter_by(simulation_id=payload_dict["simulation_id"]).first()

        if not simulation:
            return yaptide_response(message="Task does not exist", code=400)
        task: TaskModel = db.session.query.filter_by(simulation_id=payload_dict["simulation_id"], task_id=payload_dict["task_id"]).first()

        if not task:
            return yaptide_response(message="Task does not exist", code=400)

        task.update_state(payload_dict["update_dict"])
        db.session.commit()

        return yaptide_response(message="Task updated", code=202)


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


def check_if_job_is_owned(job_id: str, user: UserModel) -> tuple[bool, str, int]:
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

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        job = get_input_files.delay(job_id=job_id)
        result: dict = job.wait()

        return yaptide_response(
            message=result['info'],
            code=200,
            content=result
        )
