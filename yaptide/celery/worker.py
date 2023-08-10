import eventlet
from celery import Celery

celery_app = Celery("celery", include=['yaptide.celery.tasks'])

if __name__ == '__main__':
    # do we really need to green and monkey patch all the modules ?
    # see https://eventlet.net/doc/patching.html#import-green for more details
    eventlet.monkey_patch()
    celery_app.start()
