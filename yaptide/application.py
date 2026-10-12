import os
import re

from flask import Flask
from flask_restful import Api
from flask_migrate import Migrate
from sqlalchemy.engine import make_url
from yaptide.persistence.models import create_all
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes


SENSITIVE_NAME_PARTS = ("SECRET", "PASS", "URI", "KEY", "TOKEN", "CREDENTIAL", "DSN", "AUTH", "COOKIE", "SALT", "BINDS")


def _loggable(key: str, value) -> str:
    """Setting value safe to log: hidden for names that suggest a secret, credentials in URLs replaced everywhere"""
    if any(part in key.upper() for part in SENSITIVE_NAME_PARTS):
        return "***"
    # e.g. CELERY_BROKER_URL=redis://:password@host
    return re.sub(r"(?<=://)[^/\s]*@", "***@", str(value))


def create_app():
    """Function starting Flask Server"""
    flask_name = __name__.split(".")[0]
    app = Flask(flask_name)
    app.logger.info("Creating Flask app %s", flask_name)

    # Print env variables
    for key, value in os.environ.items():
        app.logger.debug("Environment variable: %s", (key, _loggable(key, value)))

    # Load configuration from environment variables
    # Load any environment variables that start with FLASK_, dropping the prefix from the env key for the config key.
    # Values are passed through a loading function to attempt to convert them to more specific types than strings.
    app.config.from_prefixed_env()
    for key, value in app.config.items():
        app.logger.debug("Flask config variable: %s", (key, _loggable(key, value)))

    if app.config.get("USE_CORS"):
        app.logger.info("enabling cors")
        from flask_cors import CORS

        cors_config = {
            "origins": ["http://127.0.0.1:3000", "http://localhost:3000"],
            "supports_credentials": True,
            "resources": {r"/*": {"origins": ["http://127.0.0.1:3000", "http://localhost:3000"]}},
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Access-Control-Allow-Origin"],
            "send_wildcard": False,
            "always_send": True,
        }

        CORS(app, **cors_config)

    database_uri = make_url(app.config["SQLALCHEMY_DATABASE_URI"]).render_as_string(hide_password=True)
    app.logger.info(f"Initializing Flask to use SQLAlchemy ORM @ {database_uri}")
    db.init_app(app)

    # Find a better solution (maybe with Flask-Migrate) to handle migration of data from past versions
    with app.app_context():
        app.logger.debug("Creating models")
        create_all()
        app.logger.debug(f"Created {len(db.metadata.tables)} tables")

    Migrate(app, db)
    api = Api(app)
    initialize_routes(api)

    return app


if __name__ == "__main__":
    create_app()
