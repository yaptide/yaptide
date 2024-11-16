from celery import Celery

celery_app = Celery("helper_worker",
                    include=['yaptide.batch.batch_methods', 'yaptide.utils.helper_tasks'],
                    task_routes={
                        'yaptide.batch.batch_methods*': {
                            'queue': 'helper'
                        },
                        'yaptide.utils.helper_tasks*': {
                            'queue': 'helper'
                        }
                    })
