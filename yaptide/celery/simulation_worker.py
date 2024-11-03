from celery import Celery

celery_app = Celery("simulation_worker",
                    include=['yaptide.celery.tasks'],
                    task_routes={'yaptide.celery.tasks*': {
                        'queue': 'simulations'
                    }})
