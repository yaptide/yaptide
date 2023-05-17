from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

import logging
import uuid

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist

from yaptide.persistence.database import db
from yaptide.persistence.models import (
    UserModel,
    SimulationModel,
    ClusterModel,
    TaskModel,
    EstimatorModel,
    PageModel
)

from yaptide.batch.batch_methods import submit_job, get_job_status, delete_job, get_job_results


class JobsBatch(Resource):
    """Class responsible for jobs via direct slurm connection"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with batch"""
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in payload_dict:
            return error_validation_response()

        clusters: list[ClusterModel] = db.session.query(ClusterModel).filter_by(user_id=user.id).all()
        if len(clusters) < 1:
            return error_validation_response({"message": "User has no clusters available"})

        filtered_clusters: list[ClusterModel] = []
        if "batch_options" in payload_dict and "cluster_name" in payload_dict["batch_options"]:
            cluster_name = payload_dict["batch_options"]["cluster_name"]
            filtered_clusters = [cluster for cluster in clusters if cluster.cluster_name == cluster_name]
        cluster = filtered_clusters[0] if len(filtered_clusters) > 0 else clusters[0]

        sim_type = (SimulationModel.SimType.SHIELDHIT.value
                    if "sim_type" not in payload_dict
                    or payload_dict["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value
                    else SimulationModel.SimType.DUMMY.value)
        payload_dict["sim_type"] = sim_type.lower()

        input_type = (SimulationModel.InputType.YAPTIDE_PROJECT.value
                      if "metadata" in payload_dict["sim_data"]
                      else SimulationModel.InputType.INPUT_FILES.value)

        # create a new simulation in the database, not waiting for the job to finish
        simulation = SimulationModel(user_id=user.id,
                                     platform=SimulationModel.Platform.BATCH.value,
                                     sim_type=sim_type,
                                     input_type=input_type,
                                     title=payload_dict.get("title", ''))
        update_key = str(uuid.uuid4())
        simulation.set_update_key(update_key)
        db.session.add(simulation)
        db.session.commit()

        result = submit_job(payload_dict=payload_dict, cluster=cluster)

        if "job_id" in result:
            job_id = result["job_id"]
            simulation.job_id = job_id

            for i in range(payload_dict["ntasks"]):
                task = TaskModel(simulation_id=simulation.id, task_id=f"{job_id}_{i+1}")
                db.session.add(task)
            db.session.commit()

            return yaptide_response(
                message="Job submitted",
                code=202,
                content=result
            )
        db.session.delete(simulation)
        db.session.commit()
        return yaptide_response(
            message="Job submission failed",
            code=500,
            content=result
        )

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method geting job's result"""
        schema = JobsBatch.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id: str = params_dict["job_id"]

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)
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

        try:
            _, _, _, cluster_name = job_id.split(":")
        except ValueError:
            return error_validation_response(content={"message": "Job ID is incorrect"})

        cluster: ClusterModel = db.session.query(ClusterModel).\
            filter_by(user_id=user.id, cluster_name=cluster_name).first()

        job_info = get_job_status(concat_job_id=job_id, cluster=cluster)
        if simulation.update_state(job_info):
            db.session.commit()

        job_info.pop("end_time", None)
        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(
            message="",
            code=200,
            content=job_info
        )

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling job"""
        schema = JobsBatch.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id: str = params_dict["job_id"]

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        try:
            _, _, _, cluster_name = job_id.split(":")
        except ValueError:
            return error_validation_response(content={"message": "Job ID is incorrect"})

        cluster: ClusterModel = db.session.query(ClusterModel).\
            filter_by(user_id=user.id, cluster_name=cluster_name).first()

        result, status_code = delete_job(concat_job_id=job_id, cluster=cluster)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )


class ResultsBatch(Resource):
    """Class responsible for returning simulation results"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method geting job's result"""
        schema = JobsBatch.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id: str = params_dict["job_id"]

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
            return yaptide_response(message=f"Results for job: {job_id}, results from db", code=200, content={"estimators": result_estimators})

        try:
            _, _, _, cluster_name = job_id.split(":")
        except ValueError:
            return error_validation_response(content={"message": "Job ID is incorrect"})

        cluster: ClusterModel = db.session.query(ClusterModel).\
            filter_by(user_id=user.id, cluster_name=cluster_name).first()

        result: dict = get_job_results(concat_job_id=job_id, cluster=cluster)
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

        logging.debug("Returning results from SLURM")
        return yaptide_response(message=f"Results for job: {job_id}, results from Slurm", code=200, content=result)
