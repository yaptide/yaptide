import json
import logging
from flask import request
from flask_restful import Resource
from yaptide.redis.redis import redis_client
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_simulation_auth_token

class TasksResource(Resource):
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
        decoded_token = decode_simulation_auth_token(payload_dict["update_key"])
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)
        redis_client.lpush('task_updates', json.dumps(payload_dict))
        logging.info("Sent task update to redis queue.")

        return yaptide_response(message="Task queued for the update", code=202)