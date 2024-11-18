from time import sleep
from yaptide.utils.helper_worker import celery_app


@celery_app.task
def terminate_unfinished_tasks(simulation_id):
    """Function for stopping tasks that wasn't finished with first try"""
    number_of_tasks = get_tasks_from_celery(simulation_id)
    previous_number_of_tasks = 0
    while number_of_tasks != previous_number_of_tasks:
        previous_number_of_tasks = number_of_tasks
        sleep(1)
        number_of_tasks = get_tasks_from_celery(simulation_id)
    celery_app.control.revoke([celery_pair['celery_id'] for celery_pair in get_tasks_from_celery(simulation_id)],
                              terminate=True,
                              signal="SIGINT")


def get_tasks_from_celery(simulation_id):
    """returns celery ids from celery based on simulation_id. Can take up to few seconds when celry is busy"""
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
        except Exception:
            retry_treshold -= 1
            continue
    return simulation_task_ids
