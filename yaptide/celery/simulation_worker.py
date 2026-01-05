import logging
import os

from celery import Celery

celery_app = Celery("simulation_worker",
                    include=['yaptide.celery.tasks'],
                    task_routes={'yaptide.celery.tasks*': {
                        'queue': 'simulations'
                    }})

result_backend = os.getenv("CELERY_RESULT_BACKEND")
if result_backend:
    celery_app.conf.result_backend = result_backend
    logging.getLogger(__name__).info("simulation_worker using result backend %s", result_backend)
else:
    logging.getLogger(__name__).warning("simulation_worker has no CELERY_RESULT_BACKEND; backend metrics disabled")
