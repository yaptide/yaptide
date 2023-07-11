from celery import Celery
import eventlet

celery_app = Celery("celery",
                    include=['yaptide.celery.tasks'])

if __name__ == '__main__':
    eventlet.monkey_patch()
    celery_app.start()
