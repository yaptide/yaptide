import logging
from flask import Flask
from flask_restful import Api
from yaptide.routes.main_routes import initialize_routes
from yaptide.persistence.database import db
from yaptide.persistence import models
from flask_cors import CORS


def create_app(config_object="yaptide.settings"):
    """Function starting Flask Server"""
    flask_name = __name__.split('.')[0]
    app = Flask(flask_name)
    logging.info("Creating Flask app %s", flask_name)
    
    app.config.from_object(config_object)
    # print flask config
    logging.info("Flask config: %s", app.config)
    
    db.init_app(app)
    CORS(app, supports_credentials=True)

    # Find a better solution (maybe with Flask-Migrate)
    # Uncomment the two lines below to update models
    with app.app_context():
        models.create_models()

    api = Api(app)
    initialize_routes(api)

    return app


if __name__ == "__main__":
    create_app()
