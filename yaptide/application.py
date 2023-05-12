from flask import Flask
from flask_restful import Api
from yaptide.routes.main_routes import initialize_routes
from yaptide.persistence.database import db
from yaptide.persistence import models
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint


def create_app(config_object="yaptide.settings"):
    """Function starting Flask Server"""
    app = Flask(__name__.split('.')[0])

    SWAGGER_URL = '/api/docs'
    API_URL = 'http://petstore.swagger.io/v2/swagger.json'

    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,  # Swagger UI static files will be mapped to '{SWAGGER_URL}/dist/'
        API_URL,
        config={  # Swagger UI config overrides
            'app_name': "yaptide"
        }
    )

    app.register_blueprint(swaggerui_blueprint)

    app.config.from_object(config_object)
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
