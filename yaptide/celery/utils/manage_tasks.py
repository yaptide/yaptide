import logging

from celery import chain, chord, group
from celery.result import AsyncResult

from yaptide.celery.tasks import merge_results, run_single_simulation, set_merging_queued_state
from yaptide.celery.simulation_worker import celery_app
from yaptide.persistence.db_methods import update_simulation_state, update_task_state
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel
from yaptide.utils.enums import EntityState
from yaptide.utils.helper_tasks import terminate_unfinished_tasks


def run_job(files_dict: dict,
            update_key: str,
            simulation_id: int,
            ntasks: int,
            celery_ids: list,
            sim_type: str = 'shieldhit') -> str:
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
            sim_type=sim_type).set(task_id=celery_ids[i]) for i in range(ntasks)
    ])

    # By setup of simulation_worker all tasks from yaptide.celery.tasks are directed to simulations queue
    # For tests to work: putting signature as second task in chord requires specifying queue
    workflow = chord(
        map_group,
        chain(set_merging_queued_state.s().set(queue="simulations"),
              merge_results.s().set(queue="simulations")))
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


def handle_cancellation_with_fetching(tasks: list[CeleryTaskModel]):
    """Function cancel tasks with feching data"""
    celery_ids_to_terminate = []
    celery_ids_to_dump_data = []
    for task in tasks:
        if task.task_state == EntityState.RUNNING.value:
            celery_ids_to_dump_data.append(task.celery_id)
        elif task.task_state in (EntityState.PENDING.value, EntityState.UNKNOWN.value):
            celery_ids_to_terminate.append(task.celery_id)
            update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})

    # terminate tasks which do not start
    celery_app.control.revoke(celery_ids_to_terminate, terminate=True, signal="SIGINT")

    # inform celery tasks end simulation subprocess and dump data from simulation
    for id in celery_ids_to_dump_data:
        result = AsyncResult(id)
        current_status = result.status
        result.backend.store_result(id, {"dump": True}, status=current_status)


def cancel_tasks_without_fetching(simulation: CelerySimulationModel, tasks: list[CeleryTaskModel]):
    """Function to cancel tasks without feching data"""
    celery_ids = [
        task.celery_id for task in tasks
        if task.task_state in [EntityState.PENDING.value, EntityState.RUNNING.value, EntityState.UNKNOWN.value]
    ]

    # Revoke the merge task first
    celery_app.control.revoke(simulation.merge_id, terminate=True, signal="SIGINT")
    celery_app.control.revoke(celery_ids, terminate=True, signal="SIGINT")

    # Update states
    update_simulation_state(simulation=simulation, update_dict={"job_state": EntityState.CANCELED.value})
    for task in tasks:
        if task.task_state in [EntityState.PENDING.value, EntityState.RUNNING.value]:
            update_task_state(task=task, update_dict={"task_state": EntityState.CANCELED.value})

    terminate_unfinished_tasks.delay(simulation_id=simulation.id)
