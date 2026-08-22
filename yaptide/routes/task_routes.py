from flask import request
from flask_restful import Resource

from yaptide.persistence.db_methods import (
    bulk_update_task_states,
    fetch_simulation_by_sim_id,
    fetch_task_by_sim_id_and_task_id,
    update_task_state,
)
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_auth_token


class TasksResource(Resource):
    """Class responsible for updating tasks"""

    @staticmethod
    def post():
        """
        Method updating task state
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "task_id": <int>,
            "update_key": <string>,
            "update_dict": <dict>
        }
        simulation_id and task_id self explanatory
        """
        payload_dict: dict = request.get_json(force=True)
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        sim_id: int = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message=f"Simulation {sim_id} does not exist", code=400)

        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)

        task = fetch_task_by_sim_id_and_task_id(sim_id=simulation.id, task_id=payload_dict["task_id"])

        if not task:
            return yaptide_response(message=f"Task {payload_dict['task_id']} does not exist", code=400)

        update_task_state(task=task, update_dict=payload_dict["update_dict"])

        return yaptide_response(message="Task updated", code=202)


class TasksBulkResource(Resource):
    """Class responsible for updating many tasks of one simulation at once"""

    @staticmethod
    def post():
        """
        Method updating state of many tasks in one request.
        Used by the aggregator running on the cluster, which batches updates
        coming from the individual simulation tasks.
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "tasks": [{"task_id": <int>, "update_dict": <dict>}, ...]
        }
        """
        payload_dict: dict = request.get_json(force=True)
        required_keys = {"simulation_id", "update_key", "tasks"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        sim_id: int = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message=f"Simulation {sim_id} does not exist", code=400)

        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)

        task_updates: list[dict] = payload_dict["tasks"]
        if not isinstance(task_updates, list):
            return yaptide_response(message="Tasks must be a list", code=400)
        for task_update in task_updates:
            if not isinstance(task_update, dict) or {"task_id", "update_dict"} != set(task_update.keys()):
                return yaptide_response(message="Each task requires exactly task_id and update_dict keys", code=400)

        updated_count = bulk_update_task_states(sim_id=simulation.id, task_updates=task_updates)

        return yaptide_response(message=f"Updated {updated_count} tasks", code=202)
