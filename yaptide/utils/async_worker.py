from celery import Celery

celery_app = Celery("celery", include=['yaptide.batch.batch_methods'], task_routes = {'yaptide.batch.batch_methods*': {'queue':'async'}})
