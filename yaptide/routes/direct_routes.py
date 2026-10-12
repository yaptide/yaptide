import logging
from collections import Counter
from datetime import datetime, timezone

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields
from uuid import uuid4

from yaptide.direct.job_manager import cancel_simulation, submit_simulation
from yaptide.persistence.db_methods import (
    add_object_to_db,
    fetch_celery_simulation_by_job_id,
    fetch_celery_tasks_by_sim_id,
    make_commit_to_db,
    update_simulation_state,
    update_task_state,
)
from yaptide.persistence.models import (
    CelerySimulationModel,
    CeleryTaskModel,
    InputModel,
    UserModel,
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import error_validation_response, yaptide_response
from yaptide.routes.utils.utils import (
    check_if_job_is_owned_and_exist,
    determine_input_type,
    make_input_dict,
    get_clamped_ntasks_value,
)
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, PlatformType


# a running simulation reports at least every minute (heartbeat), a merge may take long for large results
ABANDONED_TASKS_SECONDS = 10 * 60
ABANDONED_MERGE_SECONDS = 60 * 60
FINAL_STATES = (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value)


def is_abandoned(simulation: CelerySimulationModel, tasks: list[CeleryTaskModel]) -> bool:
    """True when an unfinished simulation has stopped reporting, i.e. its supervisor died or Ray was restarted"""
    if simulation.job_state in FINAL_STATES or simulation.job_state == EntityState.UNKNOWN.value:
        return False
    update_times = [task.last_update_time for task in tasks if task.last_update_time]
    if not update_times:
        return False
    last_update = max(time if time.tzinfo else time.replace(tzinfo=timezone.utc) for time in update_times)
    limit = (
        ABANDONED_MERGE_SECONDS if all(task.task_state in FINAL_STATES for task in tasks) else ABANDONED_TASKS_SECONDS
    )
    return (datetime.now(timezone.utc) - last_update).total_seconds() > limit


class JobsDirect(Resource):
    """Class responsible for simulations run directly on the Ray cluster"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Submit simulation job to the Ray cluster"""
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

        # create a new simulation in the database, not waiting for the job to finish
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + str(uuid4()) + PlatformType.DIRECT.value
        simulation = CelerySimulationModel(
            user_id=user.id,
            job_id=job_id,
            sim_type=payload_dict["sim_type"],
            input_type=input_type,
            title=payload_dict.get("title", ""),
        )
        add_object_to_db(simulation)
        update_key = encode_simulation_auth_token(simulation.id)
        logging.info("Simulation %d created and inserted into DB", simulation.id)
        logging.debug("Update key set to %s", update_key)

        input_dict = make_input_dict(payload_dict=payload_dict, input_type=input_type)
        # create tasks in the database in the default PENDING state
        requested_primaries = input_dict["number_of_all_primaries"] // payload_dict["ntasks"]
        for i in range(payload_dict["ntasks"]):
            task = CeleryTaskModel(simulation_id=simulation.id, task_id=i, requested_primaries=requested_primaries)
            add_object_to_db(task, make_commit=False)
        make_commit_to_db()

        # stored before the start: the results handler reads the input, and a short simulation may finish quickly
        input_model = InputModel(simulation_id=simulation.id)
        input_model.data = input_dict
        add_object_to_db(input_model)

        # the supervisor on the Ray cluster runs the simulation to the end and reports back over HTTP
        try:
            simulation.merge_id = submit_simulation(
                simulation_id=simulation.id,
                update_key=update_key,
                files_dict=input_dict["input_files"],
                ntasks=payload_dict["ntasks"],
                sim_type=payload_dict["sim_type"],
            )
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Submitting simulation %d to the Ray cluster failed", simulation.id)
            update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.FAILED.value})
            return yaptide_response(message="Simulation could not be started, try again later", code=503)

        if simulation.update_state({"job_state": EntityState.PENDING.value}):
            make_commit_to_db()

        return yaptide_response(message="Task started", code=202, content={"job_id": simulation.job_id})

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
        job_id = param_dict["job_id"]
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        # find appropriate simulation in the database
        simulation = fetch_celery_simulation_by_job_id(job_id=job_id)

        tasks = fetch_celery_tasks_by_sim_id(sim_id=simulation.id)
        if is_abandoned(simulation, tasks):
            logging.warning(
                "Simulation %d stopped reporting, its supervisor is gone - marking it failed", simulation.id
            )
            end_time = datetime.utcnow().isoformat(sep=" ")
            for task in tasks:
                update_task_state(task=task, update_dict={"task_state": EntityState.FAILED.value, "end_time": end_time})
            update_simulation_state(
                simulation=simulation, update_dict={"job_state": EntityState.FAILED.value, "end_time": end_time}
            )

        job_tasks_status = [task.get_status_dict() for task in tasks]

        if simulation.job_state in (EntityState.COMPLETED.value, EntityState.FAILED.value):
            return yaptide_response(
                message=f"Job state: {simulation.job_state}",
                code=200,
                content={
                    "job_state": simulation.job_state,
                    "job_tasks_status": job_tasks_status,
                },
            )

        job_info = {"job_state": simulation.job_state}
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

        try:
            if not cancel_simulation(simulation_id=simulation.id):
                logging.warning("Supervisor of simulation %d not found, marking it canceled anyway", simulation.id)
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Cancelling simulation %d on the Ray cluster failed, marking it canceled", simulation.id)
        tasks = fetch_celery_tasks_by_sim_id(sim_id=simulation.id)
        update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.CANCELED.value})
        for task in tasks:
            if task.task_state in [EntityState.PENDING.value, EntityState.RUNNING.value]:
                update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})
        return yaptide_response(message="Cancelled sucessfully", code=200)
