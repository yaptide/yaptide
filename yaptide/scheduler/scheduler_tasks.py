from datetime import datetime
import json
import logging
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, fetch_task_by_sim_id_and_task_id, update_tasks_states
from yaptide.redis.redis import get_redis_client
from yaptide.scheduler.scheduler import scheduler

def save_tasks_progres_from_redis():
    redis_client = get_redis_client()
    messages = redis_client.lpop('task_updates', count = 1000)
    if messages == None or len(messages) == 0:
        logging.info('No tasks received from redis')
        return
    start = datetime.now()
    payload_dicts: list[dict] = [json.loads(message) for message in messages]
    required_keys = {"simulation_id", "task_id", "update_key", "update_dict"}
    tasks_to_update = []
    payload_dicts.reverse() #to process data from oldest to newest - in case of receiving many updates for one task
    with scheduler.app.app_context():
        for payload_dict in payload_dicts:
            if required_keys != set(payload_dict.keys()):
                diff = required_keys.difference(set(payload_dict.keys()))
                logging.warning(f"Missing keys in JSON payload: {diff}")
                continue

            sim_id: int = payload_dict["simulation_id"]
            simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

            if not simulation:
                logging.warning(f"Simulation {sim_id} does not exist")
                continue
            
            task = fetch_task_by_sim_id_and_task_id(sim_id=simulation.id, task_id=payload_dict["task_id"])

            if not task:
                logging.warning(f"Simulation {sim_id}: task {payload_dict['task_id']} does not exist")
                continue
            tasks_to_update.append((task, payload_dict["update_dict"]))
        update_tasks_states(tasks_to_update)
    finish = datetime.now()
    elapsed = (finish - start).total_seconds()
    logging.info(f"Tasks processed: {len(messages)}, tasks updated: {len(tasks_to_update)}, time elapsed: {elapsed}s")
    logging.info("Successfully updated tasks")

