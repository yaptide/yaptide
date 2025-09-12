import os
import logstash
import logging

from flask import Flask
from flask_restful import Api
from flask_migrate import Migrate
from yaptide.persistence.models import create_all
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes


def create_app():
    """Function starting Flask Server"""
    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)

    logstash_host = os.getenv("LOGSTASH_HOST", "logstash")
    logstash_port = int(os.getenv("LOGSTASH_PORT", 5001))

    try:
        logstash_handler = logstash.TCPLogstashHandler(logstash_host, logstash_port, version=1)
        logstash_handler.setLevel(logging.DEBUG)
        app.logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
        app.logger.addHandler(logstash_handler)
        logging.getLogger().addHandler(logstash_handler)
        app.logger.debug("Logstash handler initialized.")
    except Exception as e:
        app.logger.error("Failed to initialize Logstash handler: %s", str(e))
        app.logger.warning("Continuing without Logstash logging.")

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
                    "origins": ["http://127.0.0.1:3000", "http://localhost:3000"]
                }
            },
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Access-Control-Allow-Origin"],
            "send_wildcard": False,
            "always_send": True,
        }

        CORS(app, **cors_config)

    app.logger.info(f"Initializing Flask to use SQLAlchemy ORM @ {app.config['SQLALCHEMY_DATABASE_URI']}")
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
