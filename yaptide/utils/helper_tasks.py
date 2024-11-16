from time import sleep
from yaptide.utils.helper_worker import celery_app
import logging


@celery_app.task
def terminate_unfinished_tasks(celery_ids, simulation_id):
    """Function for stopping tasks that wasn't finished with first try"""

    celery_app.control.revoke([celery_pair['celery_id'] for celery_pair in get_tasks_from_celery(simulation_id)],
                              terminate=True,
                              signal="SIGINT")


def get_tasks_from_celery(simulation_id):
    """returns celery ids from celery based on simulation_id. This function usually takes up to few seconds when celry is busy with tasks"""
    simulation_task_ids = []

    retry_treshold = 10
    while retry_treshold > 0:
        # Sometimes celery_app.control is None
        try:
            for simulation in celery_app.control.inspect().active(
            )['celery@yaptide-simulation-worker'] + celery_app.control.inspect().reserved(
            )['celery@yaptide-simulation-worker']:
                if simulation['kwargs']['simulation_id'] == simulation_id:
                    simulation_task_ids.append({
                        "celery_id": simulation['id'],
                        "task_id": simulation['kwargs']['task_id']
                    })
            break
        except:
            retry_treshold -= 1
            continue
    return simulation_task_ids
