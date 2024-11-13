import logging
import redis
import json
import base64

from celery import chord, group
from celery.result import AsyncResult

from yaptide.celery.tasks import merge_results, run_single_simulation
from yaptide.celery.simulation_worker import celery_app
from yaptide.persistence.db_methods import fetch_task_by_sim_id_and_task_id, update_task_state, update_simulation_state
from yaptide.utils.enums import EntityState


def stop_tasks_in_worker(simulation):
    ids_in_worker = get_tasks_from_celery(simulation_id=simulation.id)
    task_ids = [task['task_id'] for task in ids_in_worker]
    celery_ids = [task['celery_id'] for task in ids_in_worker]
    tasks_celery = [fetch_task_by_sim_id_and_task_id(simulation.id, task_id) for task_id in task_ids]

    result: dict = cancel_job(merge_id=simulation.merge_id, celery_ids=celery_ids)

    if "merge" in result:
        update_simulation_state(simulation=simulation, update_dict=result["merge"])
        for task_index, task in enumerate(tasks_celery):
            update_task_state(task=task, update_dict=result["tasks"][task_index])

        return result
    return None


def decode_ids(redis_task_items):
    array_ids = []
    for item in redis_task_items:
        item_data = json.loads(item)
        body_encoded = item_data["body"]
        decoded_body = base64.b64decode(body_encoded)
        body_data = json.loads(decoded_body)
        kwargs = body_data[1]
        array_ids.append({"task_id": int(kwargs.get("task_id")), "simulation_id": int(kwargs.get("simulation_id"))})
    return array_ids


def delete_tasks_from_redis(simulation_id):
    client = redis.StrictRedis(host='yaptide_redis', decode_responses=True)

    key = "simulations"
    items = client.lrange(key, 0, -1)

    id_pairs = decode_ids(items)

    redis_task_ids = [pair['task_id'] for pair in id_pairs]
    for task_id in redis_task_ids:
        task = fetch_task_by_sim_id_and_task_id(simulation_id, task_id)
        update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})

    items_to_remain = [item for index, item in enumerate(items) if id_pairs[index]['simulation_id'] != simulation_id]
    client.delete(key)  # Delete existing list
    for item in items_to_remain:
        client.rpush(key, item)  # Add filtered items back to the list


def run_job(files_dict: dict, update_key: str, simulation_id: int, ntasks: int, sim_type: str = 'shieldhit') -> str:
    """Runs asynchronous simulation job"""
    logging.debug("Starting run_simulation task for %d tasks", ntasks)
    logging.debug("Simulation id: %d", simulation_id)
    logging.debug("Update key: %s", update_key)
    map_group = group([
        run_single_simulation.s(
            files_dict=files_dict,  # simulation input, keys: filenames, values: file contents
            task_id=i,
            update_key=update_key,
            simulation_id=simulation_id,
            sim_type=sim_type) for i in range(ntasks)
    ])

    workflow = chord(map_group,
                     merge_results.s().set(queue="simulations")
                     )  # For tests to work: putting signature as second task in chord requires specifying queue

    job: AsyncResult = workflow.delay()

    return job.id


def get_task_status(job_id: str, state_key: str) -> dict:
    """Gets status of each task in the workflow"""
    job = AsyncResult(id=job_id, app=celery_app)
    job_state: str = translate_celery_state_naming(job.state)

    # we still need to convert string to enum and operate later on Enum
    result = {state_key: job_state}
    if job_state == EntityState.FAILED.value:
        result["message"] = str(job.info)
    if "end_time" in job.info:
        result["end_time"] = job.info["end_time"]
    return result


def get_job_status(merge_id: str, celery_ids: list[str]) -> dict:
    """
    Returns simulation state, results are not returned here
    Simulation may consist of multiple tasks, so we need to check all of them
    """
    result = {
        "merge": get_task_status(merge_id, "job_state"),
        "tasks": [get_task_status(job_id, "task_state") for job_id in celery_ids]
    }

    return result


def get_tasks_from_celery(simulation_id):
    """returns celery ids from celery based on simulation_id"""
    simulation_task_ids = []

    for simulation in celery_app.control.inspect().active(
    )['celery@yaptide-simulation-worker'] + celery_app.control.inspect().reserved()['celery@yaptide-simulation-worker']:
        if simulation['kwargs']['simulation_id'] == simulation_id:
            simulation_task_ids.append({"celery_id": simulation['id'], "task_id": simulation['kwargs']['task_id']})
    return simulation_task_ids


def cancel_job(merge_id: str, celery_ids: list[str]) -> dict:
    """Cancels simulation"""

    def cancel_task(job_id: str, state_key: str) -> dict:
        """Cancels (if possible) every task in the workflow"""
        if not job_id:
            return {state_key: EntityState.UNKNOWN.value, "message": "No celery job_id. Skipping."}
        job = AsyncResult(id=job_id, app=celery_app)
        job_state: str = translate_celery_state_naming(job.state)

        if job_state in [EntityState.CANCELED.value, EntityState.COMPLETED.value, EntityState.FAILED.value]:
            logging.warning("Cannot cancel job %s which is already %s", job_id, job_state)
            return {state_key: job_state, "message": f"Job already {job_state}"}
        try:
            celery_app.control.revoke(job_id, terminate=True, signal="SIGINT")
        except Exception as e:  # skipcq: PYL-W0703
            logging.error("Cannot cancel job %s, due to %s", job_id, e)
            return {
                state_key: job_state,
                "message": f"Cannot cancel job {job_id}, leaving at current state {job_state}"
            }

        return {state_key: EntityState.CANCELED.value, "message": f"Job {job_id} canceled"}

    result = {
        "merge": cancel_task(merge_id, "job_state"),
        "tasks": [cancel_task(job_id, "task_state") for job_id in celery_ids]
    }
    return result


def get_job_results(job_id: str) -> dict:
    """Returns simulation results"""
    job = AsyncResult(id=job_id, app=celery_app)
    if "result" not in job.info:
        return {}
    return job.info.get("result")


def translate_celery_state_naming(job_state: str) -> str:
    """Function translating celery states' names to ones used in YAPTIDE"""
    if job_state in ["RECEIVED", "RETRY"]:
        return EntityState.PENDING.value
    if job_state in ["PROGRESS", "STARTED"]:
        return EntityState.RUNNING.value
    if job_state in ["FAILURE"]:
        return EntityState.FAILED.value
    if job_state in ["REVOKED"]:
        return EntityState.CANCELED.value
    if job_state in ["SUCCESS"]:
        return EntityState.COMPLETED.value
    # Others are the same
    return job_state
