from flask import request
from flask_restful import Resource

from yaptide.persistence import result_storage
from yaptide.persistence.db_methods import (
    bulk_update_task_states,
    fetch_simulation_by_sim_id,
    fetch_task_by_sim_id_and_task_id,
    update_task_state,
)
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.routes.utils.utils import FINAL_STATES, update_state_from_tasks


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
        if not isinstance(payload_dict, dict):
            return yaptide_response(message="Payload must be a JSON object", code=400)
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        sim_id: int = payload_dict["simulation_id"]
        task_id = payload_dict["task_id"]
        if not all(isinstance(number, int) and not isinstance(number, bool) for number in (sim_id, task_id)):
            return yaptide_response(message="simulation_id and task_id must be integers", code=400)
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
        # most reports carry only progress; the state of the simulation depends only on the states of its tasks
        if "task_state" in payload_dict["update_dict"]:
            update_state_from_tasks(simulation)

        return yaptide_response(message="Task updated", code=202)


class TasksBulkResource(Resource):
    """Class responsible for updating many tasks of one simulation at once"""

    @staticmethod
    def post():  # skipcq: PY-R1000
        """
        Method updating state of many tasks in one request.
        Kept for jobs submitted before tasks reported through object storage (yaptide/batch/watcher.py).
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "tasks": [{"task_id": <int>, "update_dict": <dict>}, ...]
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if not isinstance(payload_dict, dict):
            return yaptide_response(message="Payload must be a JSON object", code=400)
        required_keys = {"simulation_id", "update_key", "tasks"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        sim_id: int = payload_dict["simulation_id"]
        if not isinstance(sim_id, int) or isinstance(sim_id, bool):
            return yaptide_response(message="simulation_id must be an integer", code=400)
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
            task_id = task_update["task_id"]
            if (
                not isinstance(task_id, int)
                or isinstance(task_id, bool)
                or not isinstance(task_update["update_dict"], dict)
            ):
                return yaptide_response(message="task_id must be an integer and update_dict a dictionary", code=400)

        updated_count = bulk_update_task_states(sim_id=simulation.id, task_updates=task_updates)
        reports_state = any("task_state" in task_update["update_dict"] for task_update in task_updates)
        if reports_state:
            update_state_from_tasks(simulation)

        return yaptide_response(message=f"Updated {updated_count} tasks", code=202)


class TaskLinksResource(Resource):
    """New signed storage links for the jobs of an HPC simulation running longer than the links last (a week)"""

    @staticmethod
    def post():
        """Body: simulation_id and update_key"""
        payload = request.get_json(force=True)
        if not isinstance(payload, dict) or not {"simulation_id", "update_key"} <= set(payload):
            return yaptide_response(message="simulation_id and update_key are required", code=400)
        if not isinstance(payload["simulation_id"], int) or isinstance(payload["simulation_id"], bool):
            return yaptide_response(message="simulation_id must be an integer", code=400)
        simulation = fetch_simulation_by_sim_id(sim_id=payload["simulation_id"])
        if simulation is None:
            return yaptide_response(message="Simulation does not exist", code=400)
        if decode_auth_token(payload["update_key"], payload_key_to_return="simulation_id") != simulation.id:
            return yaptide_response(message="Invalid update key", code=400)
        if simulation.job_state in FINAL_STATES or not result_storage.configured():
            return yaptide_response(message=f"No links for a simulation in {simulation.job_state}", code=409)
        return yaptide_response(message="Links", code=200, content={"links": result_storage.job_links(simulation.id)})
