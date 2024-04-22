import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from yaptide.persistence.models import create_all
from yaptide.persistence.database import db
from yaptide.admin import git_submodules


def create_app():
    """Function starting Flask Server"""
    git_submodules.check_submodules()

    # Main_routes module is importing (in-directly) the converter module which is cloned as submodule.
    # Lack of this submodule would result in the ModuleNotFoundError.
    from yaptide.routes.main_routes import initialize_routes

    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)
    app.logger.info("Creating Flask app %s", flask_name)

    # Print env variables
    for item in os.environ.items():
        app.logger.debug("Environment variable: %s", item)

    # Load configuration from environment variables
    # Load any environment variables that start with FLASK_, dropping the prefix from the env key for the config key.
    # Values are passed through a loading function to attempt to convert them to more specific types than strings.
    app.config.from_prefixed_env()
    for item in app.config.items():
        app.logger.debug("Flask config variable: %s", item)

    if app.config.get('USE_CORS'):
        app.logger.info("enabling cors")
        from flask_cors import CORS
        cors_config = {
            "origins": ["http://127.0.0.1:3000", "http://localhost:3000"],
            "supports_credentials": True,
            "resources": {
                r"/*": {
                    "origins": ["http://127.0.0.1:3000","http://localhost:3000"]
                }
            },
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Access-Control-Allow-Origin"],
            "send_wildcard": False,
            "always_send": True,
        }

        CORS(app, **cors_config)

    SWAGGER_URL = '/api/docs'
    API_URL = '/static/openapi.yaml'

    swaggerui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL, config={'app_name': "yaptide"})

    app.register_blueprint(swaggerui_blueprint)

    app.logger.info(f"Initializing Flask to use SQLAlchemy ORM @ {app.config['SQLALCHEMY_DATABASE_URI']}")
    db.init_app(app)

    # Find a better solution (maybe with Flask-Migrate) to handle migration of data from past versions
    with app.app_context():
        app.logger.debug("Creating models")
        create_all()
        app.logger.debug(f"Created {len(db.metadata.tables)} tables")

    api = Api(app)
    initialize_routes(api)

    return app


if __name__ == "__main__":
    create_app()
