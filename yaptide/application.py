from flask import Flask
from flask_restful import Api
from yaptide.routes import initialize_routes
from yaptide.persistence.database import db
<<<<<<< HEAD
from yaptide.persistence import models
=======
from yaptide.persistence.models import create_models
>>>>>>> 453880b (Refactor of project structure, application and database)


def create_app(config_object="yaptide.settings"):
    app = Flask(__name__.split('.')[0])
    app.config.from_object(config_object)
    db.init_app(app)

    # TODO: Find a better solution (maybe with Flask-Migrate)
    # Uncomment the two lines below to update models
<<<<<<< HEAD
    with app.app_context():
        models.create_models()
=======
    # with app.app_context():
    #     create_models()
>>>>>>> 453880b (Refactor of project structure, application and database)

    api = Api(app)
    initialize_routes(api)
    return app


if __name__ == "__main__":
    create_app()
