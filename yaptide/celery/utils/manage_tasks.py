from celery import group, chord
from celery.result import AsyncResult
import logging

from yaptide.celery.tasks import run_single_simulation, merge_results
from yaptide.celery.worker import celery_app

from yaptide.utils.enums import EntityState


def run_job(files_dict: dict, update_key: str, simulation_id: int, ntasks: int) -> str:
    """Runs simulation job"""
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


def get_job_status(job_id: str) -> dict:
    """
    Returns simulation state, results are not returned here
    Simulation may consist of multiple tasks, so we need to check all of them
    """
    # Here we ask Celery (via Redis) for job state
    job = AsyncResult(id=job_id, app=celery_app)
    job_state: str = translate_celery_state_naming(job.state)

    # we still need to convert string to enum and operate later on Enum
    result = {
        "job_state": job_state
    }
    if job_state == EntityState.FAILED.value:
        result["message"] = str(job.info)
    elif "end_time" in job.info:
        result["end_time"] = job.info["end_time"]

    return result


def cancel_job(merge_id: str, celery_ids: list[str]) -> dict:
    """Cancels simulation"""
    for job_id in celery_ids:
        job = AsyncResult(id=job_id, app=celery_app)
        job_state: str = translate_celery_state_naming(job.state)

        if job_state in [EntityState.CANCELLED.value,
                         EntityState.COMPLETED.value,
                         EntityState.FAILED.value]:
            logging.warning("Cannot cancel job %s which is already %s", job_id, job_state)
            continue
        try:
            celery_app.control.revoke(job_id, terminate=True, signal="SIGINT")
        except:  # skipcq: FLK-E722
            logging.error("Cannot cancel job %s", job_id)
    
    merge_job = AsyncResult(id=merge_id, app=celery_app)
    merge_job_state: str = translate_celery_state_naming(merge_job.state)

    if merge_job_state in [EntityState.CANCELLED.value,
                        EntityState.COMPLETED.value,
                        EntityState.FAILED.value]:
        logging.warning("Cannot cancel job %s which is already %s", merge_job, merge_job_state)
        return {
            "job_state": merge_job_state,
            "message": "Job already completed"
        }
    try:
        celery_app.control.revoke(merge_job, terminate=True, signal="SIGINT")
    except:  # skipcq: FLK-E722
        logging.error("Cannot cancel job %s", merge_job)


    return {
        "job_state": EntityState.CANCELLED.value,
        "message": "Job cancelled"
    }


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
        return EntityState.CANCELLED.value
    if job_state in ["SUCCESS"]:
        return EntityState.COMPLETED.value
    # Others are the same
    return job_state
