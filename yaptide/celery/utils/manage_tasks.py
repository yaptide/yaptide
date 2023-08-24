import logging

from celery import chord, group
from celery.result import AsyncResult

from yaptide.celery.tasks import merge_results, run_single_simulation
from yaptide.celery.worker import celery_app
from yaptide.utils.enums import EntityState


def run_job(files_dict: dict, update_key: str, simulation_id: int, ntasks: int) -> str:
    """Runs asynchronous simulation job"""
    map_group = group([
        run_single_simulation.s(
            files_dict=files_dict,
            task_id=f"{simulation_id}_{i}",
            update_key=update_key,
            simulation_id=simulation_id
        ) for i in range(ntasks)
    ])

    workflow = chord(map_group, merge_results.s())

    job: AsyncResult = workflow.delay()

    return job.id


def get_job_status(merge_id: str, celery_ids: list[str]) -> dict:
    """
    Returns simulation state, results are not returned here
    Simulation may consist of multiple tasks, so we need to check all of them
    """
    # Here we ask Celery (via Redis) for job state
    def get_task_status(job_id: str, state_key: str) -> dict:
        """Gets status of each task in the workflow"""
        job = AsyncResult(id=job_id, app=celery_app)
        job_state: str = translate_celery_state_naming(job.state)

        # we still need to convert string to enum and operate later on Enum
        result = {
            state_key: job_state
        }
        if job_state == EntityState.FAILED.value:
            result["message"] = str(job.info)
        if "end_time" in job.info:
            result["end_time"] = job.info["end_time"]
        return result

    result = {
        "merge": get_task_status(merge_id, "job_state"),
        "tasks": [get_task_status(job_id, "task_state") for job_id in celery_ids]
    }

    return result


def cancel_job(merge_id: str, celery_ids: list[str]) -> dict:
    """Cancels simulation"""
    def cancel_task(job_id: str, state_key: str) -> dict:
        """Cancels (if possible) every task in the workflow"""
        job = AsyncResult(id=job_id, app=celery_app)
        job_state: str = translate_celery_state_naming(job.state)

        if job_state in [EntityState.CANCELED.value,
                         EntityState.COMPLETED.value,
                         EntityState.FAILED.value]:
            logging.warning("Cannot cancel job %s which is already %s", job_id, job_state)
            return {
                state_key: job_state,
                "message": f"Job already {job_state}"
            }
        try:
            celery_app.control.revoke(job_id, terminate=True, signal="SIGINT")
        except Exception as e:  # skipcq: PYL-W0703
            logging.error("Cannot cancel job %s, due to %s", job_id, e)
            return {
                state_key: job_state,
                "message": f"Cannot cancel job {job_id}, leaving at current state {job_state}"
            }

        return {
            state_key: EntityState.CANCELED.value,
            "message": f"Job {job_id} canceled"
        }

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
