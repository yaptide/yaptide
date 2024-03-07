import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from sqlalchemy import create_engine

from yaptide.persistence import models
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes


def create_app():
    """Function starting Flask Server"""
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

    SWAGGER_URL = '/api/docs'
    API_URL = '/static/openapi.yaml'

    swaggerui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL, config={'app_name': "yaptide"})

    app.register_blueprint(swaggerui_blueprint)

    app.logger.info("Initializing database")

    db.init_app(app)

    # Find a better solution (maybe with Flask-Migrate)
    # Uncomment the two lines below to update models
    with app.app_context():
        app.logger.info("Creating models")
        from yaptide.persistence import models
        engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], echo=True)
        models.Base.metadata.create_all(bind=engine)
        #db.create_all()
        app.logger.info("Models created")
        # models.create_models()

    db_uri = os.environ.get('FLASK_SQLALCHEMY_DATABASE_URI')
    app.logger.info(f'Connecting to URI: {db_uri}')
    if not db_uri:
        app.logger.info(f'Database URI: {db_uri} not set - aborting', err=True)
    engine = db.create_engine(db_uri, echo=True)
    try:
        con = engine.connect()

        #db.create_all(bind=engine)

        metadata = db.MetaData()
        metadata.create_all(bind=engine)
        metadata.reflect(bind=engine)
    except db.exc.OperationalError:
        app.logger.info(f'Connection to db {db_uri} failed', err=True)

    app.logger.info("Tables in database: %d", len(metadata.tables))
    for table in metadata.tables:
        app.logger.info(f"Table: {table}")

    api = Api(app)
    initialize_routes(api)

    return app


if __name__ == "__main__":
    create_app()
