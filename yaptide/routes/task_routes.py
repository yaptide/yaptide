from datetime import datetime
import json
import logging
import os
from flask import request
from flask_restful import Resource
from yaptide.redis.redis import redis_client
from yaptide.persistence.db_methods import (fetch_simulation_by_sim_id,
                                            fetch_task_by_sim_id_and_task_id,
                                            update_task_state)
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
        start_time_1 = datetime.now()
        payload_dict: dict = request.get_json(force=True)
        
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        if required_keys != set(payload_dict.keys()):
            diff = required_keys.difference(set(payload_dict.keys()))
            return yaptide_response(message=f"Missing keys in JSON payload: {diff}", code=400)

        start_time_2 = datetime.now()
        sim_id: int = payload_dict["simulation_id"]
        decoded_token = decode_simulation_auth_token(payload_dict["update_key"])
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)
        start_time_3 = datetime.now()
        redis_client.lpush('task_updates', json.dumps(payload_dict))
        start_time_4 = datetime.now()
        logging.info("Sent task update to redis queue.")

        # Calculate and log durations
        duration_1_2 = (start_time_2 - start_time_1).total_seconds()
        duration_2_3 = (start_time_3 - start_time_2).total_seconds()
        duration_3_4 = (start_time_4 - start_time_3).total_seconds()
        total = (start_time_4 - start_time_1).total_seconds()
        logger = logging.getLogger("performance_test")
        logger.info(f"{duration_1_2},{duration_2_3},{duration_3_4},{total}")


        return yaptide_response(message="Task queued for the update", code=202)