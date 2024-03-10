import logging
import os
import subprocess

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint

from yaptide.persistence import models
from yaptide.persistence.database import db


def create_app():
    """Function starting Flask Server"""
    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)
    logging.info("Creating Flask app %s", flask_name)

    check_submodules()

    from yaptide.routes.main_routes import initialize_routes

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

    return app

def check_submodules():
    try:
        result = subprocess.run(["git", "submodule", "status"], capture_output=True, text=True, check=True)

        for line in result.stdout.splitlines():
            if line.startswith('-') or line.startswith('+'):
                raise RuntimeError("Submodules are missing! Please clone with submodules or use: git submodule update --init --recursive")

    except subprocess.CalledProcessError as e:
        logging.error(f"Error running 'git submodule status': {e}")
if __name__ == "__main__":
    create_app()
