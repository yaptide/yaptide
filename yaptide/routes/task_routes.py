import json
import logging
from flask import request
from flask_restful import Resource
from yaptide.redis.redis import get_redis_client
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_auth_token

class TasksResource(Resource):
    """Class responsible for updating tasks"""

    @staticmethod
    def post():
        """
        Method queuing tasks for update.
        Authenticates requests and submit it to the redis queue for udpdate.
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
        
        # Check if all required parameters are in payload
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        #Check if update_dict is a valid JWT token that is assigned to requested simulation_id 
        sim_id: int = payload_dict["simulation_id"]
        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)
        
        # Redis queue is used because of high load of this endpoint, single updates are uneffective
        # Batched updates are processed by a background job in yaptide.scheduler.scheduler_tasks
        # that listens to redis queue.
        redis_client = get_redis_client()
        redis_client.lpush('task_updates', json.dumps(payload_dict))
        logging.info("Sent task update to redis queue.")

        return yaptide_response(message="Task queued for the update", code=202)