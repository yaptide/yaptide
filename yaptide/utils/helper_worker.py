import logging
import os

from celery import Celery

celery_app = Celery("helper_worker",
                    include=['yaptide.batch.batch_methods', 'yaptide.utils.helper_tasks'],
                    task_routes={
                        'yaptide.batch.batch_methods*': {
                            'queue': 'helper'
                        },
                        'yaptide.utils.helper_tasks*': {
                            'queue': 'helper-short'
                        }
                    })

result_backend = os.getenv("CELERY_RESULT_BACKEND")
if result_backend:
    celery_app.conf.result_backend = result_backend
    logging.getLogger(__name__).info("helper_worker using result backend %s", result_backend)
else:
    logging.getLogger(__name__).warning("helper_worker has no CELERY_RESULT_BACKEND; backend metrics disabled")
