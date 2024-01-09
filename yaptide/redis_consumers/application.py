import logging
import os
from threading import Thread
from flask import Flask
from yaptide.persistence import  models
from yaptide.persistence.database import db
from yaptide.redis_consumers.redis_consumer_base import RedisConsumerBase
from yaptide.redis_consumers.task_progress_consumer import TaskProgressConsumerThread

def run_consumers(app: Flask) -> None:
    consumers = [TaskProgressConsumerThread(app)] #TODO: Implement consumer for task update queue and put here
    for consumer in consumers:
        consumer.start()

    for consumer in consumers:
        consumer.join()

def create_app() -> None:
    logging.basicConfig(level = logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')
    app = Flask(__name__)
    logging.info("Creating Flask app %s", __name__)

    # Print env variables
    for item in os.environ.items():
        logging.debug("Environment variable: %s", item)

    # Load configuration from environment variables
    # Load any environment variables that start with FLASK_, dropping the prefix from the env key for the config key.
    # Values are passed through a loading function to attempt to convert them to more specific types than strings.
    app.config.from_prefixed_env()
    for item in app.config.items():
        logging.debug("Flask config variable: %s", item)
    
    
    db.init_app(app)
    with app.app_context():
        models.create_models()
    Thread(target=run_consumers, args=(app,)).start()
    return app

if __name__ == "__main__":
    app = create_app()


    