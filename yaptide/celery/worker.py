from celery import Celery

celery_app = Celery(
    "celery-app",
    backend='redis://localhost',
    broker='redis://localhost')
