import logging
from flask import Flask
from flask_restful import Api
from yaptide.routes.main_routes import initialize_routes
from yaptide.persistence.database import db
from yaptide.persistence import models
from flask_swagger_ui import get_swaggerui_blueprint


def create_app():
    """Function starting Flask Server"""
    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)
    logging.info("Creating Flask app %s", flask_name)

    # Load configuration from environment variables
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


if __name__ == "__main__":
    create_app()
