import uuid
from datetime import datetime

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.persistence.database import db
from yaptide.persistence.db_methods import (
    fetch_all_clusters,
    fetch_batch_simulation_by_job_id,
    fetch_batch_tasks_by_sim_id,
    note_watching,
    update_simulation_state,
    update_task_state,
)
from yaptide.persistence.models import (  # skipcq: FLK-E101
    BatchSimulationModel,
    BatchTaskModel,
    ClusterModel,
    InputModel,
    KeycloakUserModel,
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import error_validation_response, yaptide_response
from yaptide.routes.utils.utils import (
    check_if_job_is_owned_and_exist,
    determine_input_type,
    make_input_dict,
    get_clamped_ntasks_value,
    job_status_content,
)
from yaptide.utils.enums import EntityState, PlatformType


class JobsBatch(Resource):
    """HPC simulations: stored here, submitted and cancelled on the cluster by the engine (yaptide/engine)"""

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

        # ensure the ntasks value is in allowed range
        payload_dict["ntasks"] = get_clamped_ntasks_value(payload_dict=payload_dict, ntasks=payload_dict["ntasks"])

        clusters = fetch_all_clusters()
        if len(clusters) < 1:
            return error_validation_response({"message": "No clusters are available"})

        filtered_clusters: list[ClusterModel] = []
        if "batch_options" in payload_dict and "cluster_name" in payload_dict["batch_options"]:
            cluster_name = payload_dict["batch_options"]["cluster_name"]
            filtered_clusters = [cluster for cluster in clusters if cluster.cluster_name == cluster_name]
        cluster = filtered_clusters[0] if len(filtered_clusters) > 0 else clusters[0]

        # the simulation, its tasks and input in one commit: the engine submits what it finds PENDING
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + str(uuid.uuid4()) + PlatformType.BATCH.value
        input_dict = make_input_dict(payload_dict=payload_dict, input_type=input_type)
        # what the engine needs to write the sbatch scripts
        input_dict["batch_options"] = payload_dict.get("batch_options") or {}
        requested_primaries = input_dict["number_of_all_primaries"] // payload_dict["ntasks"]
        # skipcq: PYL-E1123
        simulation = BatchSimulationModel(
            user_id=user.id,
            cluster_id=cluster.id,
            job_id=job_id,
            sim_type=payload_dict["sim_type"],
            input_type=input_type,
            title=payload_dict.get("title", ""),
            job_state=EntityState.PENDING.value,
        )
        # the relationships do not cascade saving, so the children are added themselves
        simulation.tasks = [
            BatchTaskModel(task_id=task_id, requested_primaries=requested_primaries)
            for task_id in range(1, payload_dict["ntasks"] + 1)
        ]
        input_model = InputModel()
        input_model.data = input_dict
        simulation.inputs = [input_model]
        db.session.add_all([simulation, input_model, *simulation.tasks])
        db.session.commit()

        return yaptide_response(message="Job waiting for submission", code=202, content={"job_id": simulation.job_id})

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()
        # the UI needs only the totals; the list of tasks stays the default for older clients
        tasks = fields.Boolean(load_default=True)

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

        # a read only: the states come from what the cluster's jobs report
        message, content = f"Job state: {simulation.job_state}", job_status_content(simulation, params_dict["tasks"])
        # the UI asks while it cannot open the status stream: the progress of the user's simulations is read often
        note_watching(user.id)
        return yaptide_response(message=message, code=200, content=content)

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

        if simulation.job_state in (
            EntityState.COMPLETED.value,
            EntityState.FAILED.value,
            EntityState.CANCELED.value,
            EntityState.UNKNOWN.value,
        ):
            return yaptide_response(
                message=f"Cannot cancel job which is in {simulation.job_state} state",
                code=200,
                content={
                    "job_state": simulation.job_state,
                },
            )

        # the engine sees the state and cancels the jobs on the cluster
        update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.CANCELED.value})
        if simulation.job_state != EntityState.CANCELED.value:
            # finished meanwhile
            return yaptide_response(
                message=f"Cannot cancel job which is in {simulation.job_state} state",
                code=200,
                content={"job_state": simulation.job_state},
            )
        for task in fetch_batch_tasks_by_sim_id(sim_id=simulation.id):
            if task.task_state in [EntityState.PENDING.value, EntityState.RUNNING.value]:
                update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})
        return yaptide_response(message="Job canceled", code=200)


class Clusters(Resource):
    """Class responsible for returning user's available clusters"""

    @staticmethod
    @requires_auth()
    def get(user: KeycloakUserModel):
        """Method returning clusters"""
        if not isinstance(user, KeycloakUserModel):
            return yaptide_response(message="User is not allowed to use this endpoint", code=403)

        clusters = fetch_all_clusters()

        result = {"clusters": [{"cluster_name": cluster.cluster_name} for cluster in clusters]}
        return yaptide_response(message="Available clusters", code=200, content=result)
