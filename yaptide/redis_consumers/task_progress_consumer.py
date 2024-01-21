from flask import Flask
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, fetch_task_by_sim_id_and_task_id, update_tasks_states
from yaptide.redis_consumers.redis_consumer_base import RedisConsumerBase
import json
from datetime import datetime

class TaskProgressConsumerThread(RedisConsumerBase):
    def __init__(self, app: Flask):
        RedisConsumerBase.__init__(self, app, "TaskProgressConsumer", "task_updates", 500)
        
    def handle_message(self, messages: list[str]) -> None:
        self.update_task_progress(messages)

    def update_task_progress(self, messages: list[str]) -> None:
        start = datetime.now()
        payload_dicts: list[dict] = [json.loads(message) for message in messages]
        required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
        tasks_to_update = []
        payload_dicts.reverse() #to process data from oldest to newest - in case of receiving many updates for one task
        with self.app.app_context():
            for payload_dict in payload_dicts:
                if required_keys != set(payload_dict.keys()):
                    diff = required_keys.difference(set(payload_dict.keys()))
                    self.log_message_error(f"Missing keys in JSON payload: {diff}")
                    continue

                sim_id: int = payload_dict["simulation_id"]
                simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

                if not simulation:
                    self.log_message_error(f"Simulation {sim_id} does not exist")
                    continue
                
                task = fetch_task_by_sim_id_and_task_id(sim_id=simulation.id, task_id=payload_dict["task_id"])

                if not task:
                    self.log_message_error(f"Simulation {sim_id}: task {payload_dict['task_id']} does not exist")
                    continue
                tasks_to_update.append((task, payload_dict["update_dict"]))
            update_tasks_states(tasks_to_update)
        finish = datetime.now()
        elapsed = (finish - start).total_seconds()
        self.log_message_info(f"Tasks processed: {len(messages)}, tasks updated: {len(tasks_to_update)}, time elapsed: {elapsed}s")
        self.log_message_info("Successfully updated tasks")