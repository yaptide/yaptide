from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

import uuid

import logging

from yaptide.persistence.database import db
from yaptide.persistence.models import UserBaseModel, SimulationModel, TaskModel, EstimatorModel, PageModel, InputModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist

from yaptide.celery.tasks import run_simulation, convert_input_files, run_single_simulation
from yaptide.celery.utils.utils import get_job_status, cancel_job, get_job_results
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries


class JobsDirect(Resource):
    """Class responsible for simulations run directly with celery"""

    @staticmethod
    @requires_auth()
    def post(user: UserBaseModel):
        """Submit simulation job to celery"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        required_keys = {"sim_type", "ntasks", "input_type"}

        if required_keys != required_keys.intersection(set(payload_dict.keys())):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        input_type = None
        if payload_dict["input_type"] == "editor":
            if "input_json" not in payload_dict:
                return error_validation_response()
            input_type = SimulationModel.InputType.EDITOR.value
        if payload_dict["input_type"] == "files":
            if "input_files" not in payload_dict:
                return error_validation_response()
            input_type = SimulationModel.InputType.FILES.value

        if input_type is None:
            return error_validation_response()

        # create a new simulation in the database, not waiting for the job to finish
        simulation = SimulationModel(user_id=user.id,
                                     platform=SimulationModel.Platform.DIRECT.value,
                                     sim_type=payload_dict["sim_type"],
                                     input_type=input_type,
                                     title=payload_dict.get("title", ''))
        update_key = str(uuid.uuid4())
        simulation.set_update_key(update_key)
        db.session.add(simulation)
        db.session.commit()
        logging.info("Simulation %d created", simulation.id)

        input_dict_to_save = {
            "input_type": input_type,
        }
        if input_type == SimulationModel.InputType.EDITOR.value:
            files_dict, number_of_all_primaries = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
            input_dict_to_save["input_json"] = payload_dict["input_json"]
        else:
            files_dict, number_of_all_primaries = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
        input_dict_to_save["number_of_all_primaries"] = number_of_all_primaries
        input_dict_to_save["input_files"] = files_dict

        # submit the job to the Celery queue
        # job = run_simulation.delay(payload_dict=payload_dict, files_dict=files_dict,
        #                            update_key=update_key, simulation_id=simulation.id)
        # simulation.job_id = job.id

        for _ in range(payload_dict["ntasks"]):
            job = run_single_simulation.delay(files_dict=files_dict, update_key=update_key, simulation_id=simulation.id)
            task_id = job.id
            task = TaskModel(simulation_id=simulation.id, task_id=task_id)
            db.session.add(task)
        input_model = InputModel(simulation_id=simulation.id)
        input_model.data = input_dict_to_save
        db.session.add(input_model)
        db.session.commit()

        return yaptide_response(message="Task started", code=202, content={'job_id': job.id})

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserBaseModel):
        """Method returning job status and results"""
        # validate request parameters and handle errors
        schema = JobsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        # get job_id from request parameters and check if user owns this job
        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        # find appropriate simulation in the database
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        tasks: list[TaskModel] = db.session.query(TaskModel).filter_by(simulation_id=simulation.id).all()

        job_tasks_status = [task.get_status_dict() for task in tasks]

        if simulation.job_state in (SimulationModel.JobState.COMPLETED.value,
                                    SimulationModel.JobState.FAILED.value):
            return yaptide_response(message=f"Job state: {simulation.job_state}",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                        "job_tasks_status": job_tasks_status,
                                    })

        # get job status from Celery, extracting status from job.info
        # this dict will be returned to the user as a response to GET request
        job_info: dict = get_job_status(job_id=job_id)

        # if simulation is not found, return error
        if simulation.update_state(job_info):
            db.session.commit()

        # remove end_time from job_info, as it is not needed in response
        job_info.pop("end_time", None)
        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message=f"Job state: {job_info['job_state']}", code=200, content=job_info)

    @staticmethod
    @requires_auth()
    def delete(user: UserBaseModel):
        """Method canceling simulation and returning status of this action"""
        schema = JobsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(
            job_id=params_dict['job_id'], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        result: dict = cancel_job(job_id=params_dict['job_id'])

        if "job_state" in result:
            db.session.query(SimulationModel).filter_by(job_id=params_dict['job_id']).delete()
            db.session.commit()
            return yaptide_response(message="", code=200, content=result)

        return error_internal_response()


class ResultsDirect(Resource):
    """Class responsible for returning simulation results"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserBaseModel):
        """Method returning job status and results"""
        schema = ResultsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        estimators: list[EstimatorModel] = db.session.query(EstimatorModel).filter_by(simulation_id=simulation.id).all()
        if len(estimators) > 0:
            logging.debug("Returning results from database")
            result_estimators = []
            for estimator in estimators:
                pages: list[PageModel] = db.session.query(PageModel).filter_by(estimator_id=estimator.id).all()
                estimator_dict = {
                    "metadata": estimator.data,
                    "name": estimator.name,
                    "pages": [page.data for page in pages]
                }
                result_estimators.append(estimator_dict)
            return yaptide_response(message=f"Results for job: {job_id}",
                                    code=200, content={"estimators": result_estimators})

        result: dict = get_job_results(job_id=job_id)
        if "estimators" not in result:
            logging.debug("Results for job %s are unavailable", job_id)
            return yaptide_response(message="Results are unavailable", code=404, content=result)

        for estimator_dict in result["estimators"]:
            estimator = EstimatorModel(name=estimator_dict["name"], simulation_id=simulation.id)
            estimator.data = estimator_dict["metadata"]
            db.session.add(estimator)
            db.session.commit()
            for page_dict in estimator_dict["pages"]:
                page = PageModel(estimator_id=estimator.id,
                                 page_number=int(page_dict["metadata"]["page_number"]))
                page.data = page_dict
                db.session.add(page)
            db.session.commit()

        logging.debug("Returning results from Celery")
        return yaptide_response(message=f"Results for job: {job_id}, results from Celery", code=200, content=result)


class ConvertInputFiles(Resource):
    """Class responsible for returning input_model files converted from front JSON"""

    @staticmethod
    @requires_auth()
    def post(_: UserBaseModel):
        """Method handling input_model files convertion"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        # Rework in later PRs to match pattern from jobs endpoint
        job = convert_input_files.delay(payload_dict=payload_dict)
        result: dict = job.wait()

        return yaptide_response(message="Converted Input Files", code=200, content=result)
