from flask import request
from flask_restful import Resource

from yaptide.persistence.db_methods import (
    fetch_simulation_by_sim_id,
    fetch_task_by_sim_id_and_task_id,
    update_task_state
)

from yaptide.routes.utils.response_templates import yaptide_response


class TaskUpdate(Resource):
    """Class responsible for updating tasks"""

    @staticmethod
    def post():
        """
        Method updating task state
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "task_id": <string>,
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

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        task = fetch_task_by_sim_id_and_task_id(sim_id=simulation.id, task_id=payload_dict["task_id"])

        if not task:
            return yaptide_response(message=f"Task {payload_dict['task_id']} does not exist", code=400)

        update_task_state(task=task, update_dict=payload_dict["update_dict"])

        return yaptide_response(message="Task updated", code=202)
