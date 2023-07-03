from datetime import datetime
import logging

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.batch.batch_methods import get_job_results
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    ClusterModel,
    EstimatorModel,
    InputModel,
    LogfilesModel,
    PageModel,
    SimulationModel,
    UserBaseModel
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import error_validation_response, yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist


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
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(id=sim_id).first()

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        for estimator_dict in payload_dict["estimators"]:
            # We forsee the possibility of the estimator being created earlier as element of partial results
            estimator: EstimatorModel = db.session.query(EstimatorModel).filter_by(
                simulation_id=sim_id, name=estimator_dict["name"]).first()

            if not estimator:
                estimator = EstimatorModel(name=estimator_dict["name"], simulation_id=simulation.id)
                estimator.data = estimator_dict["metadata"]
                db.session.add(estimator)
                db.session.commit()

            for page_dict in estimator_dict["pages"]:
                page: PageModel = db.session.query(PageModel).filter_by(
                    estimator_id=estimator.id, page_number=int(page_dict["metadata"]["page_number"])).first()

                page_existed = bool(page)
                if not page_existed:
                    # create new page
                    page = PageModel(page_number=int(page_dict["metadata"]["page_number"]), estimator_id=estimator.id)
                # we always update the data
                page.data = page_dict
                if not page_existed:
                    # if page was created, we add it to the session
                    db.session.add(page)
            db.session.commit()

        if simulation.update_state({
                "job_state": SimulationModel.JobState.COMPLETED.value,
                "end_time": datetime.utcnow().isoformat(sep=" ")
            }):
            db.session.commit()
        return yaptide_response(message="Results saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserBaseModel):
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

        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        estimators: list[EstimatorModel] = db.session.query(EstimatorModel).filter_by(simulation_id=simulation.id).all()
        if len(estimators) == 0:
            if simulation.platform == "DIRECT":  # also CODE TO REMOVE
                return yaptide_response(message="Results are unavailable", code=404)
            # Code below is for backward compatibility with old method of saving results
            # later on we are going to remove it because it's functionality will be covered
            # by the post method
            # BEGIN CODE TO REMOVE
            try:
                _, _, _, cluster_name = job_id.split(":")
            except ValueError:
                return error_validation_response(content={"message": "Job ID is incorrect"})

            cluster: ClusterModel = db.session.query(ClusterModel).\
                filter_by(cluster_name=cluster_name).first()

            result: dict = get_job_results(concat_job_id=job_id, user=user, cluster=cluster)
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
            estimators: list[EstimatorModel] = db.session.query(EstimatorModel).\
                filter_by(simulation_id=simulation.id).all()
            # END CODE TO REMOVE

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
        return yaptide_response(message=f"Results for job: {job_id}", code=200,
                                content={"estimators": result_estimators})


class SimulationInputs(Resource):
    """Class responsible for returning simulation input"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserBaseModel):
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

        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        input_model: InputModel = db.session.query(InputModel).filter_by(simulation_id=simulation.id).first()
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
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(id=sim_id).first()

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        logfiles = LogfilesModel(simulation_id=simulation.id)
        logfiles.data = payload_dict["logfiles"]
        db.session.add(logfiles)
        db.session.commit()

        return yaptide_response(message="Log files saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserBaseModel):
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

        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

        logfile: LogfilesModel = db.session.query(LogfilesModel).filter_by(simulation_id=simulation.id).first()
        if not logfile:
            return yaptide_response(message="Logfiles are unavailable", code=404)

        logging.debug("Returning logfiles from database")

        return yaptide_response(message="Logfiles", code=200, content={"logfiles": logfile.data})
