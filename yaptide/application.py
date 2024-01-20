import logging
import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint

from yaptide.persistence import models
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes


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

    # Find a better solution (maybe with Flask-Migrate)
    # Uncomment the two lines below to update models
    with app.app_context():
        models.create_models()

    api = Api(app)
    initialize_routes(api)

    performance_test_logger = logging.getLogger('performance_test')
    performance_test_logger.setLevel(logging.INFO)
    log_file_path = "performance_tests.log"
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(formatter)
    performance_test_logger.addHandler(file_handler)

    return app


if __name__ == "__main__":
    create_app()
