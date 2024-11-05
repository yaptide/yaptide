import uuid
from datetime import datetime

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.batch.batch_methods import delete_job, get_job_status, submit_job
from yaptide.persistence.db_methods import (add_object_to_db, fetch_all_clusters, fetch_batch_simulation_by_job_id,
                                            fetch_batch_tasks_by_sim_id, fetch_cluster_by_id, make_commit_to_db,
                                            update_simulation_state, update_task_state)
from yaptide.persistence.models import (  # skipcq: FLK-E101
    BatchSimulationModel, BatchTaskModel, ClusterModel, InputModel, KeycloakUserModel)
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import (error_validation_response, error_internal_response,
                                                     yaptide_response)
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist, determine_input_type, make_input_dict
from yaptide.utils.enums import EntityState, PlatformType


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

        input_type = determine_input_type(payload_dict)

        if input_type is None:
            return error_validation_response()

        clusters = fetch_all_clusters()
        if len(clusters) < 1:
            return error_validation_response({"message": "No clusters are available"})

        filtered_clusters: list[ClusterModel] = []
        if "batch_options" in payload_dict and "cluster_name" in payload_dict["batch_options"]:
            cluster_name = payload_dict["batch_options"]["cluster_name"]
            filtered_clusters = [cluster for cluster in clusters if cluster.cluster_name == cluster_name]
        cluster = filtered_clusters[0] if len(filtered_clusters) > 0 else clusters[0]

        # create a new simulation in the database, not waiting for the job to finish
        job_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + str(uuid.uuid4()) + PlatformType.BATCH.value
        # skipcq: PYL-E1123
        simulation = BatchSimulationModel(user_id=user.id,
                                          cluster_id=cluster.id,
                                          job_id=job_id,
                                          sim_type=payload_dict["sim_type"],
                                          input_type=input_type,
                                          title=payload_dict.get("title", ''))
        add_object_to_db(simulation)
        update_key = encode_simulation_auth_token(simulation.id)

        input_dict = make_input_dict(payload_dict=payload_dict, input_type=input_type)

        submit_job.delay(payload_dict=payload_dict,
                         files_dict=input_dict["input_files"],
                         userId=user.id,
                         clusterId=cluster.id,
                         sim_id=simulation.id,
                         update_key=update_key)

        for i in range(payload_dict["ntasks"]):
            task = BatchTaskModel(simulation_id=simulation.id, task_id=str(i + 1))
            add_object_to_db(task, False)

        input_model = InputModel(simulation_id=simulation.id)
        input_model.data = input_dict
        add_object_to_db(input_model)
        if simulation.update_state({"job_state": EntityState.PENDING.value}):
            make_commit_to_db()

        return yaptide_response(message="Job waiting for submission", code=202, content={'job_id': simulation.job_id})

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
        simulation = fetch_batch_simulation_by_job_id(job_id=job_id)

        tasks = fetch_batch_tasks_by_sim_id(sim_id=simulation.id)

        job_tasks_status = [task.get_status_dict() for task in tasks]

        if simulation.job_state in (EntityState.COMPLETED.value, EntityState.FAILED.value):
            return yaptide_response(message=f"Job state: {simulation.job_state}",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                        "job_tasks_status": job_tasks_status,
                                    })

        cluster = fetch_cluster_by_id(cluster_id=simulation.cluster_id)

        job_info = get_job_status(simulation=simulation, user=user, cluster=cluster)
        update_simulation_state(simulation=simulation, update_dict=job_info)

        job_info.pop("end_time", None)
        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message="", code=200, content=job_info)

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

        simulation = fetch_batch_simulation_by_job_id(job_id=job_id)

        if simulation.job_state in (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value,
                                    EntityState.UNKNOWN.value):
            return yaptide_response(message=f"Cannot cancel job which is in {simulation.job_state} state",
                                    code=200,
                                    content={
                                        "job_state": simulation.job_state,
                                    })

        cluster = fetch_cluster_by_id(cluster_id=simulation.cluster_id)

        result, status_code = delete_job(simulation=simulation, user=user, cluster=cluster)
        if status_code != 200:
            return error_internal_response(content=result)

        update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.CANCELED.value})

        tasks = fetch_batch_tasks_by_sim_id(sim_id=simulation.id)

        for task in tasks:
            update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})

        return yaptide_response(message="", code=status_code, content=result)


class Clusters(Resource):
    """Class responsible for returning user's available clusters"""

    @staticmethod
    @requires_auth()
    def get(user: KeycloakUserModel):
        """Method returning clusters"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

        clusters = fetch_all_clusters()

        result = {'clusters': [{'cluster_name': cluster.cluster_name} for cluster in clusters]}
        return yaptide_response(message='Available clusters', code=200, content=result)
