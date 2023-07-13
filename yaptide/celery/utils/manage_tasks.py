import logging

from celery import group, chord
from celery.result import AsyncResult, GroupResult

from yaptide.celery.tasks import run_single_simulation, merge_results
from yaptide.celery.worker import celery_app

from yaptide.persistence.models import SimulationModel


def run_job(files_dict: dict, update_key: str, simulation_id: int, ntasks: int) -> str:
    map_group = group([
        run_single_simulation.s(
            files_dict=files_dict,
            task_id=i,
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
    if job_state == SimulationModel.JobState.FAILED.value:
        result["message"] = str(job.info)
    elif "end_time" in job.info:
        result["end_time"] = job.info["end_time"]

    return result


def cancel_job(job_id: str) -> dict:
    """Cancels simulation"""
    job = AsyncResult(id=job_id, app=celery_app)
    job_state: str = translate_celery_state_naming(job.state)

    if job_state in [SimulationModel.JobState.CANCELLED.value,
                     SimulationModel.JobState.COMPLETED.value,
                     SimulationModel.JobState.FAILED.value]:
        return {"message": f"Cannot cancel job which is already {job_state}"}
    try:
        celery_app.control.revoke(job_id, terminate=True, signal="SIGINT")
    except:
        return {"message": "Failed to cancel job"}

    return {
        "job_state": SimulationModel.JobState.CANCELLED.value,
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
        return SimulationModel.JobState.PENDING.value
    if job_state in ["PROGRESS", "STARTED"]:
        return SimulationModel.JobState.RUNNING.value
    if job_state in ["FAILURE"]:
        return SimulationModel.JobState.FAILED.value
    if job_state in ["REVOKED"]:
        return SimulationModel.JobState.CANCELLED.value
    if job_state in ["SUCCESS"]:
        return SimulationModel.JobState.COMPLETED.value
    # Others are the same
    return job_state
