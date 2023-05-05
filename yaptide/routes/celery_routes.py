from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from datetime import datetime
import uuid

import logging

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel, TaskModel, ResultModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

from yaptide.celery.tasks import (run_simulation, convert_input_files, get_input_files, cancel_simulation)
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

        # we need to handle better lower and upper case
        sim_type = (SimulationModel.SimType.SHIELDHIT.value if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value else
                    SimulationModel.SimType.DUMMY.value)

        input_type = (SimulationModel.InputType.YAPTIDE_PROJECT.value
                      if "metadata" in payload_dict["sim_data"] else SimulationModel.InputType.INPUT_FILES.value)

        # create a new simulation in the database, not waiting for the job to finish
        simulation = SimulationModel(user_id=user.id,
                                     platform=SimulationModel.Platform.DIRECT.value,
                                     sim_type=sim_type,
                                     input_type=input_type,
                                     title=payload_dict.get("title", ''))
        update_key = str(uuid.uuid4())
        simulation.set_update_key(update_key)
        db.session.add(simulation)
        db.session.commit()

        # submit the job to the Celery queue
        job = run_simulation.delay(payload_dict=payload_dict, update_key=update_key, simulation_id=simulation.id)
        simulation.job_id = job.id

        for i in range(payload_dict["ntasks"]):
            task = TaskModel(simulation_id=simulation.id, task_id=f"{job.id}_{i+1}")
            db.session.add(task)
        db.session.commit()

        return yaptide_response(message="Task started", code=202, content={'job_id': job.id})

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()

    # why get is a static method ? it could be a class method and have direct access to cls.APIParametersSchema
    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning job status and results"""
        # validate request parameters and handle errors
        schema = JobsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        # get job_id from request parameters and check if user owns this job
        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        # find appropriate simulation in the database
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()
        if simulation is None:
            return yaptide_response(message="Simulation not found", code=404)

        tasks: list[TaskModel] = db.session.query(TaskModel).filter_by(simulation_id=simulation.id).all()

        job_tasks_status = [task.get_status_dict() for task in tasks]

        if simulation.job_state == SimulationModel.JobState.COMPLETED.value:
            return yaptide_response(message=f"Job state: {simulation.job_state}",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                        "job_tasks_status": job_tasks_status,
                                    })

        # get job status from Celery, extracting status from job.info
        # this dict will be returned to the user as a response to GET request
        job_info: dict = get_job_status_as_dict(job_id=job_id)

        # if simulation is not found, return error
        simulation.update_state(job_info)
        db.session.commit()

        # remove end_time from job_info, as it is not needed in response
        job_info.pop("end_time", None)
        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message=f"Job state: {job_info['job_state']}", code=200, content=job_info)

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        try:
            payload_dict: dict = JobsDirect.APIParametersSchema().load(request.get_json(force=True))
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

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    # why get is a static method ? it could be a class method and have direct access to cls.APIParametersSchema
    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning job status and results"""
        schema = ResultsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()
        if simulation is None:
            return yaptide_response(message="Simulation not found", code=404)

        results: list[ResultModel] = db.session.query(ResultModel).filter_by(simulation_id=simulation.id).all()
        if len(results) > 0:
            # later on we would like to return persistent results
            logging.debug("Returning results from database")
        result: dict = get_job_results(job_id=job_id)
        # later on we would like to add results to database here
        if "result" not in result:
            logging.debug("Results for job %s are unavailable", job_id)
            return yaptide_response(message="Results are unavailable", code=404, content=result)

        if "end_time" in result and simulation.end_time is None:
            simulation.end_time = datetime.strptime(result['end_time'], '%Y-%m-%dT%H:%M:%S.%f')
            db.session.commit()

        result.pop("end_time", None)

        logging.debug("Returning results from Celery")
        return yaptide_response(message=f"Results for job: {job_id}", code=200, content=result)


class ConvertInputFiles(Resource):
    """Class responsible for returning input files converted from front JSON"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(_: UserModel):
        """Method handling input files convertion"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        sim_type = (SimulationModel.SimType.SHIELDHIT.value if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value else
                    SimulationModel.SimType.DUMMY.value)

        # Rework in later PRs to match pattern from jobs endpoint
        job = convert_input_files.delay(payload_dict={"sim_type": sim_type.lower(), "sim_data": payload_dict})
        result: dict = job.wait()

        return yaptide_response(message="Converted Input Files", code=200, content=result)


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

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    # why get is a static method ? it could be a class method and have direct access to cls.APIParametersSchema
    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning simulation input files"""
        schema = SimulationInputs.APIParametersSchema()
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

        return yaptide_response(message=result['info'], code=200, content=result)
