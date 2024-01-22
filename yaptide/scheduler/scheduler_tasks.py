from datetime import datetime
import json
import logging
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, fetch_task_by_sim_id_and_task_id, update_tasks_states
from yaptide.redis.redis import get_redis_client

def save_tasks_progres_from_redis_job(app):
    """
    Save tasks updates that are enqueued to redis queue "task_updates".
    Main goal of this job is to process batched updates in database
    and reduce load of POST /tasks endpoint.
    """
    redis_client = get_redis_client()
    # Pop 1000 or less messages from left end of queue.
    messages = redis_client.lpop('task_updates', count = 1000)
    # Queue can be empty if there are no tasks to update
    if messages == None or len(messages) == 0:
        logging.info('No tasks received from redis')
        return
    
    start = datetime.now()
    
    # Deserialize all received task updates messages
    payload_dicts: list[dict] = [json.loads(message) for message in messages]
    tasks_to_update = []
    # Required to process data from oldest to newest - to prevent overriding new state by old for one task
    payload_dicts.reverse()
    with app.app_context():
        for payload_dict in payload_dicts:
            sim_id = payload_dict["simulation_id"]
            task_id = payload_dict["task_id"]
            task = fetch_task_by_sim_id_and_task_id(sim_id = sim_id, task_id = task_id)
            if not task:
                logging.warning(f"Simulation {sim_id}: task {payload_dict['task_id']} does not exist")
                continue
            tasks_to_update.append((task, payload_dict["update_dict"]))
        # Batch update of all accepted tasks
        update_tasks_states(tasks_to_update)
    finish = datetime.now()
    elapsed = (finish - start).total_seconds()
    logging.info(f"Tasks processed: {len(messages)}, tasks updated: {len(tasks_to_update)}, time elapsed: {elapsed}s")
    logging.info("Successfully updated tasks")

