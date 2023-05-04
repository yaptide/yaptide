from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import SimulationModel, TaskModel

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
        required_keys = {"simulation_id", "task_id", "auth_key", "update_dict"}
        if not required_keys.intersection(set(payload_dict.keys())):
            return yaptide_response(message="Incomplete JSON data", code=400)

        simulation: SimulationModel = db.session.query.filter_by(simulation_id=payload_dict["simulation_id"]).first()

        if not simulation:
            return yaptide_response(message="Task does not exist", code=400)

        if not simulation.check_update_key(payload_dict["update_key"]):
            return yaptide_response(message="Invalid update key", code=400)

        task: TaskModel = db.session.query.filter_by(simulation_id=payload_dict["simulation_id"],
                                                     task_id=payload_dict["task_id"]).first()

        if not task:
            return yaptide_response(message="Task does not exist", code=400)

        task.update_state(payload_dict["update_dict"])
        db.session.commit()

        return yaptide_response(message="Task updated", code=202)