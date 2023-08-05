import uuid
import logging

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.batch.batch_methods import delete_job, get_job_status, submit_job
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    ClusterModel, InputModel, KeycloakUserModel, SimulationModel, TaskModel)  # skipcq: FLK-E101
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import error_validation_response, yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries


class JobsBatch(Resource):
    """Class responsible for jobs via direct slurm connection"""

    @staticmethod
    @requires_auth()
    def post(user: KeycloakUserModel):
        """Method handling running shieldhit with batch"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

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

        clusters: list[ClusterModel] = db.session.query(ClusterModel).all()
        if len(clusters) < 1:
            return error_validation_response({"message": "No clusters are available"})

        filtered_clusters: list[ClusterModel] = []
        if "batch_options" in payload_dict and "cluster_name" in payload_dict["batch_options"]:
            cluster_name = payload_dict["batch_options"]["cluster_name"]
            filtered_clusters = [cluster for cluster in clusters if cluster.cluster_name == cluster_name]
        cluster = filtered_clusters[0] if len(filtered_clusters) > 0 else clusters[0]

        # create a new simulation in the database, not waiting for the job to finish
        simulation = SimulationModel(user_id=user.id,
                                     platform=SimulationModel.Platform.BATCH.value,
                                     sim_type=payload_dict["sim_type"],
                                     input_type=input_type,
                                     title=payload_dict.get("title", ''))
        update_key = str(uuid.uuid4())
        simulation.set_update_key(update_key)
        db.session.add(simulation)
        db.session.commit()

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

        result = submit_job(payload_dict=payload_dict, files_dict=files_dict, user=user,
                            cluster=cluster, sim_id=simulation.id, update_key=update_key)

        logging.warning("%s", result)

        if "job_id" in result:
            job_id = result["job_id"]
            simulation.job_id = job_id

            for i in range(payload_dict["ntasks"]):
                task = TaskModel(simulation_id=simulation.id, task_id=f"{job_id}_{i}")
                db.session.add(task)
            input_model = InputModel(simulation_id=simulation.id)
            input_model.data = input_dict_to_save
            db.session.add(input_model)
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
    @requires_auth()
    def get(user: KeycloakUserModel):
        """Method geting job's result"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

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

        simulation

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
            filter_by(cluster_name=cluster_name).first()

        job_info = get_job_status(concat_job_id=job_id, user=user, cluster=cluster)
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
    @requires_auth()
    def delete(user: KeycloakUserModel):
        """Method canceling job"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

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
            filter_by(cluster_name=cluster_name).first()

        result, status_code = delete_job(concat_job_id=job_id, user=user, cluster=cluster)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )


class Clusters(Resource):
    """Class responsible for returning user's available clusters"""

    @staticmethod
    @requires_auth()
    def get(user: KeycloakUserModel):
        """Method returning clusters"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

        clusters: list[ClusterModel] = db.session.query(ClusterModel).all()

        result = {
            'clusters': [
                {
                    'cluster_name': cluster.cluster_name
                }
                for cluster in clusters
            ]
        }
        return yaptide_response(message='Available clusters', code=200, content=result)
