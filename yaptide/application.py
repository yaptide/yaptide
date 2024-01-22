import logging
import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint

from yaptide.persistence import models
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes
from yaptide.scheduler.scheduler import scheduler
from yaptide.scheduler.scheduler_tasks import save_tasks_progres_from_redis

def create_app():
    """Function starting Flask Server"""
    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)
    logging.info("Creating Flask app %s", flask_name)

    # Print env variables
    for item in os.environ.items():
        logging.debug("Environment variable: %s", item)

    # Load configuration from environment variables
    # Load any environment variables that start with FLASK_, dropping the prefix from the env key for the config key.
    # Values are passed through a loading function to attempt to convert them to more specific types than strings.
    app.config.from_prefixed_env()
    for item in app.config.items():
        logging.debug("Flask config variable: %s", item)

    SWAGGER_URL = '/api/docs'
    API_URL = '/static/openapi.yaml'

    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={'app_name': "yaptide"}
    )

    app.register_blueprint(swaggerui_blueprint)

    db.init_app(app)
    scheduler.init_app(app)
    scheduler.start()

    # Find a better solution (maybe with Flask-Migrate)
    # Uncomment the two lines below to update models
    with app.app_context():
        models.create_models()
        scheduler.add_job("save_tasks_progres_from_redis", save_tasks_progres_from_redis, trigger="interval", seconds=2)
    api = Api(app)
    initialize_routes(api)

    return app


if __name__ == "__main__":
    create_app()
