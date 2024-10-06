from celery import Celery

celery_app = Celery("celery", include=['yaptide.celery.tasks'], task_routes = {'yaptide.celery.tasks*': {'queue':'simulations'}})
