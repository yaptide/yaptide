from flask import Flask
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, fetch_task_by_sim_id_and_task_id, update_task_state
from yaptide.redis_consumers.redis_consumer_base import RedisConsumerBase
import json

class TaskProgressConsumerThread(RedisConsumerBase):
    def __init__(self, app: Flask):
        RedisConsumerBase.__init__(self, app, "TaskProgressConsumer", "task_updates", 50)
        
    def handle_message(self, messages: list[str]) -> None:
        self.update_task_progress(messages)

    def update_task_progress(self, messages: list[str]) -> None:
        payload_dicts: list[dict] = [json.loads(message) for message in messages]
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        for payload_dict in payload_dicts:
            if required_keys != set(payload_dict.keys()):
                diff = required_keys.difference(set(payload_dict.keys()))
                self.log_message_error(f"Missing keys in JSON payload: {diff}")
                return

            sim_id: int = payload_dict["simulation_id"]
            with self.app.app_context():
                simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

                if not simulation:
                    self.log_message_error(f"Simulation {sim_id} does not exist")
                    return

                if not simulation.check_update_key(payload_dict["update_key"]):
                    self.log_message_error("Invalid update key")
                    return
                
                task = fetch_task_by_sim_id_and_task_id(sim_id=simulation.id, task_id=payload_dict["task_id"])

                if not task:
                    self.log_message_error(f"Task {payload_dict['task_id']} does not exist")
                    return

                update_task_state(task=task, update_dict=payload_dict["update_dict"])
                self.log_message_info("Successfully updated task")