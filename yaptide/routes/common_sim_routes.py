from datetime import datetime
import logging
from collections import Counter

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.batch.batch_methods import get_job_results
from yaptide.persistence.db_methods import (
    add_object_to_db,
    make_commit_to_db,
    fetch_simulation_by_job_id,
    fetch_cluster_by_id,
    fetch_simulation_by_sim_id,
    fetch_tasks_by_sim_id,
    fetch_estimators_by_sim_id,
    fetch_estimator_by_sim_id_and_est_name,
    fetch_pages_by_estimator_id,
    fetch_page_by_est_id_and_page_number,
    fetch_input_by_sim_id,
    update_simulation_state,
    fetch_logfiles_by_sim_id
)
from yaptide.persistence.models import (
    EstimatorModel,
    LogfilesModel,
    PageModel,
    BatchSimulationModel,
    UserModel
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist
from yaptide.utils.enums import EntityState


class Jobs(Resource):
    """Class responsible for managing common jobs"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning info about job"""
        schema = Jobs.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        # get job_id from request parameters and check if user owns this job
        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        tasks = fetch_tasks_by_sim_id(sim_id=simulation.id)

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

        update_simulation_state(simulation=simulation, update_dict=job_info)

        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message=f"Job state: {job_info['job_state']}", code=200, content=job_info)


class SimulationResults(Resource):
    """Class responsible for managing results"""

    @staticmethod
    def post():
        """
        Method for saving results
        Used by the jobs at the end of simulation
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "estimators": <dict>
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if {"simulation_id", "update_key", "estimators"} != set(payload_dict.keys()):
            return yaptide_response(message="Incomplete JSON data", code=400)

        sim_id = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        for estimator_dict in payload_dict["estimators"]:
            # We forsee the possibility of the estimator being created earlier as element of partial results
            estimator = fetch_estimator_by_sim_id_and_est_name(sim_id=sim_id, est_name=estimator_dict["name"])

            if not estimator:
                estimator = EstimatorModel(name=estimator_dict["name"], simulation_id=simulation.id)
                estimator.data = estimator_dict["metadata"]
                add_object_to_db(estimator)

            for page_dict in estimator_dict["pages"]:
                page = fetch_page_by_est_id_and_page_number(
                    est_id=estimator.id, page_number=int(page_dict["metadata"]["page_number"]))

                page_existed = bool(page)
                if not page_existed:
                    # create new page
                    page = PageModel(page_number=int(page_dict["metadata"]["page_number"]), estimator_id=estimator.id)
                # we always update the data
                page.data = page_dict
                if not page_existed:
                    # if page was created, we add it to the session
                    add_object_to_db(page, False)
            make_commit_to_db()
        update_simulation_state(simulation=simulation, update_dict={
            "job_state": EntityState.COMPLETED.value,
            "end_time": datetime.utcnow().isoformat(sep=" ")
            })
        return yaptide_response(message="Results saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning job status and results"""
        schema = SimulationResults.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        estimators = fetch_estimators_by_sim_id(sim_id=simulation.id)
        if len(estimators) == 0:
            if not isinstance(simulation, BatchSimulationModel):  # also CODE TO REMOVE
                return yaptide_response(message="Results are unavailable", code=404)
            # Code below is for backward compatibility with old method of saving results
            # later on we are going to remove it because it's functionality will be covered
            # by the post method
            # BEGIN CODE TO REMOVE

            cluster = fetch_cluster_by_id(cluster_id=simulation.cluster_id)

            result: dict = get_job_results(simulation=simulation, user=user, cluster=cluster)
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
            estimators = fetch_estimators_by_sim_id(sim_id=simulation.id)
            # END CODE TO REMOVE

        logging.debug("Returning results from database")
        result_estimators = []
        for estimator in estimators:
            pages = fetch_pages_by_estimator_id(est_id=estimator.id)
            estimator_dict = {
                "metadata": estimator.data,
                "name": estimator.name,
                "pages": [page.data for page in pages]
            }
            result_estimators.append(estimator_dict)
        return yaptide_response(message=f"Results for job: {job_id}", code=200,
                                content={"estimators": result_estimators})


class SimulationInputs(Resource):
    """Class responsible for returning simulation input"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning simulation input"""
        schema = SimulationInputs.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)
        job_id = param_dict['job_id']

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        input_model = fetch_input_by_sim_id(sim_id=simulation.id)
        if not input_model:
            return yaptide_response(message="Input of simulation is unavailable", code=404)

        return yaptide_response(message="Input of simulation", code=200, content={"input": input_model.data})


class SimulationLogfiles(Resource):
    """Class responsible for managing logfiles"""

    @staticmethod
    def post():
        """
        Method for saving logfiles
        Used by the jobs when the simulation fails
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "logfiles": <dict>
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if {"simulation_id", "update_key", "logfiles"} != set(payload_dict.keys()):
            return yaptide_response(message="Incomplete JSON data", code=400)

        sim_id = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        logfiles = LogfilesModel(simulation_id=simulation.id)
        logfiles.data = payload_dict["logfiles"]
        add_object_to_db(logfiles)

        return yaptide_response(message="Log files saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning job status and results"""
        schema = SimulationResults.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        logfile = fetch_logfiles_by_sim_id(sim_id=simulation.id)
        if not logfile:
            return yaptide_response(message="Logfiles are unavailable", code=404)

        logging.debug("Returning logfiles from database")

        return yaptide_response(message="Logfiles", code=200, content={"logfiles": logfile.data})
