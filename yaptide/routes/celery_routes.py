import logging
import uuid
from collections import Counter
from datetime import datetime

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.celery.tasks import convert_input_files
from yaptide.celery.utils.manage_tasks import (cancel_job, get_job_results,
                                               run_job)
from yaptide.persistence.db_methods import (add_object_to_db,
                                            fetch_celery_simulation_by_job_id,
                                            fetch_celery_tasks_by_sim_id,
                                            fetch_estimators_by_sim_id,
                                            fetch_pages_by_estimator_id,
                                            make_commit_to_db,
                                            update_simulation_state,
                                            update_task_state)
from yaptide.persistence.models import (CelerySimulationModel, CeleryTaskModel,
                                        EstimatorModel, InputModel, PageModel,
                                        UserModel)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import (error_internal_response,
                                                     error_validation_response,
                                                     yaptide_response)
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist, determine_input_type, make_input_dict
from yaptide.utils.enums import EntityState, PlatformType


class JobsDirect(Resource):
    """Class responsible for simulations run directly with celery"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Submit simulation job to celery"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        required_keys = {"sim_type", "ntasks", "input_type"}

        if required_keys != required_keys.intersection(set(payload_dict.keys())):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        input_type = determine_input_type(payload_dict)

        if input_type is None:
            return error_validation_response()

        # create a new simulation in the database, not waiting for the job to finish
        job_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + str(uuid.uuid4()) + PlatformType.DIRECT.value
        simulation = CelerySimulationModel(user_id=user.id,
                                           job_id=job_id,
                                           sim_type=payload_dict["sim_type"],
                                           input_type=input_type,
                                           title=payload_dict.get("title", ''))
        update_key = str(uuid.uuid4())
        simulation.set_update_key(update_key)
        add_object_to_db(simulation)
        logging.info("Simulation %d created and inserted into DB", simulation.id)
        logging.debug("Update key set to %s", update_key)

        input_dict = make_input_dict(payload_dict=payload_dict, input_type=input_type)

        # submit the asynchronous job to celery
        simulation.merge_id = run_job(input_dict["input_files"], update_key, simulation.id, payload_dict["ntasks"],
                                      payload_dict["sim_type"])

        # create tasks in the database in the default PENDING state
        for i in range(payload_dict["ntasks"]):
            task = CeleryTaskModel(simulation_id=simulation.id, task_id=f"{simulation.id}_{i}")
            add_object_to_db(task, make_commit=False)

        input_model = InputModel(simulation_id=simulation.id)
        input_model.data = input_dict
        add_object_to_db(input_model)
        if simulation.update_state({"job_state": EntityState.PENDING.value}):
            make_commit_to_db()

        return yaptide_response(message="Task started", code=202, content={'job_id': simulation.job_id})

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
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
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        # find appropriate simulation in the database
        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)

        tasks = fetch_celery_tasks_by_sim_id(sim_id=simulation.id)

        job_tasks_status = [task.get_status_dict() for task in tasks]

        if simulation.job_state in (EntityState.COMPLETED.value,
                                    EntityState.FAILED.value):
            return yaptide_response(message=f"Job state: {simulation.job_state}",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                        "job_tasks_status": job_tasks_status,
                                    })

        job_info = {
            "job_state": simulation.job_state
        }
        status_counter = Counter([task["task_state"] for task in job_tasks_status])
        if status_counter[EntityState.PENDING.value] == len(job_tasks_status):
            job_info["job_state"] = EntityState.PENDING.value
        elif status_counter[EntityState.FAILED.value] == len(job_tasks_status):
            job_info["job_state"] = EntityState.FAILED.value
        elif status_counter[EntityState.RUNNING.value] > 0:
            job_info["job_state"] = EntityState.RUNNING.value

        # if simulation is not found, return error
        update_simulation_state(simulation=simulation, update_dict=job_info)

        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message=f"Job state: {job_info['job_state']}", code=200, content=job_info)

    @staticmethod
    @requires_auth()
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        schema = JobsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id = params_dict['job_id']

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(
            job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)

        if simulation.job_state in (EntityState.COMPLETED.value,
                                    EntityState.FAILED.value,
                                    EntityState.CANCELED.value,
                                    EntityState.UNKNOWN.value):
            return yaptide_response(message=f"Cannot cancel job which is in {simulation.job_state} state",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                    })

        tasks = fetch_celery_tasks_by_sim_id(sim_id=simulation.id)

        celery_ids = [task.celery_id for task in tasks]

        result: dict = cancel_job(merge_id=simulation.merge_id, celery_ids=celery_ids)

        if "merge" in result:
            update_simulation_state(simulation=simulation, update_dict=result["merge"])
            for i, task in enumerate(tasks):
                update_task_state(task=task, update_dict=result["tasks"][i])

            return yaptide_response(message="", code=200, content=result)

        return error_internal_response()


class ResultsDirect(Resource):
    """Class responsible for returning simulation results"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
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

        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)

        estimators: list[EstimatorModel] = fetch_estimators_by_sim_id(sim_id=simulation.id)
        if len(estimators) > 0:
            logging.debug("Returning results from database")
            result_estimators = []
            for estimator in estimators:
                pages: list[PageModel] = fetch_pages_by_estimator_id(est_id=estimator.id)
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
            add_object_to_db(estimator)
            for page_dict in estimator_dict["pages"]:
                page = PageModel(estimator_id=estimator.id,
                                 page_number=int(page_dict["metadata"]["page_number"]))
                page.data = page_dict
                add_object_to_db(page, False)
            make_commit_to_db()

        logging.debug("Returning results from Celery")
        return yaptide_response(message=f"Results for job: {job_id}, results from Celery", code=200, content=result)


class ConvertResource(Resource):
    """Class responsible for returning input_model files converted from front JSON"""

    @staticmethod
    @requires_auth()
    def post(_: UserModel):
        """Method handling input_model files convertion"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        # Rework in later PRs to match pattern from jobs endpoint
        job = convert_input_files.delay(payload_dict=payload_dict)
        result: dict = job.wait()

        return yaptide_response(message="Converted Input Files", code=200, content=result)
