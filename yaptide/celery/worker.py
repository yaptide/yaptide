from celery import Celery

celery_app = Celery("celery",
                    backend='redis://localhost',
                    broker='redis://localhost',
                    include=['yaptide.celery.tasks'])

if __name__ == '__main__':
    celery_app.start()