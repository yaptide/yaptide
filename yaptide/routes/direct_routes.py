import logging
from datetime import datetime

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields
from uuid import uuid4

from yaptide.persistence.database import db
from yaptide.persistence.db_methods import (
    fetch_celery_simulation_by_job_id,
    fetch_celery_tasks_by_sim_id,
    update_simulation_state,
    update_task_state,
)
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel, InputModel, UserModel
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
from yaptide.utils.sim_utils import output_size_error


class JobsDirect(Resource):
    """Simulations run directly on the server: stored here, run by the engine (yaptide/engine)"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Stores a simulation for the engine to run"""
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

        # the simulation, its tasks and input in one commit: the engine starts what it finds PENDING
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + str(uuid4()) + PlatformType.DIRECT.value
        input_dict = make_input_dict(payload_dict=payload_dict, input_type=input_type)
        too_large = output_size_error(input_dict["input_files"], payload_dict["ntasks"])
        if too_large:
            return yaptide_response(message=too_large, code=400)
        requested_primaries = input_dict["number_of_all_primaries"] // payload_dict["ntasks"]
        simulation = CelerySimulationModel(
            user_id=user.id,
            job_id=job_id,
            sim_type=payload_dict["sim_type"],
            input_type=input_type,
            title=payload_dict.get("title", ""),
            job_state=EntityState.PENDING.value,
        )
        # the relationships do not cascade saving, so the children are added themselves
        simulation.tasks = [
            CeleryTaskModel(task_id=task_id, requested_primaries=requested_primaries)
            for task_id in range(payload_dict["ntasks"])
        ]
        input_model = InputModel()
        input_model.data = input_dict
        simulation.inputs = [input_model]
        db.session.add_all([simulation, input_model, *simulation.tasks])
        db.session.commit()
        logging.info("Simulation %d stored for the engine", simulation.id)

        return yaptide_response(message="Task started", code=202, content={"job_id": simulation.job_id})

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()
        # the UI needs only the totals; the list of tasks stays the default for older clients
        tasks = fields.Boolean(load_default=True)

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
        job_id = param_dict["job_id"]
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)
        # a read only: the state follows the tasks when they report, not when someone looks
        content = job_status_content(simulation, with_tasks=param_dict["tasks"])
        return yaptide_response(message=f"Job state: {simulation.job_state}", code=200, content=content)

    @staticmethod
    @requires_auth()
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        schema = JobsDirect.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id = params_dict["job_id"]

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)

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

        # the engine sees the state and stops the tasks
        update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.CANCELED.value})
        if simulation.job_state != EntityState.CANCELED.value:
            # finished meanwhile
            return yaptide_response(
                message=f"Cannot cancel job which is in {simulation.job_state} state",
                code=200,
                content={"job_state": simulation.job_state},
            )
        for task in fetch_celery_tasks_by_sim_id(sim_id=simulation.id):
            if task.task_state in [EntityState.PENDING.value, EntityState.RUNNING.value]:
                update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})
        return yaptide_response(message="Cancelled sucessfully", code=200)
