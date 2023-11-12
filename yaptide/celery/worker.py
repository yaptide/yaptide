from celery import Celery

celery_app = Celery("celery", include=['yaptide.celery.tasks'])
