from celery import Celery

celery_app = Celery("helper_worker",
                    include=['yaptide.batch.batch_methods'],
                    task_routes={'yaptide.batch.batch_methods*': {
                        'queue': 'helper'
                    }})
