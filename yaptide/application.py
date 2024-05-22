import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from yaptide.persistence.models import create_all
from yaptide.persistence.database import db
from yaptide.routes.main_routes import initialize_routes
from yaptide.scheduler.scheduler import run_scheduler
from yaptide.admin import git_submodules
import logging

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
                    "origins": ["http://127.0.0.1:3000", "http://localhost:3000"]
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
    if not app.config['TESTING']:
        run_scheduler(app)

    # Find a better solution (maybe with Flask-Migrate) to handle migration of data from past versions
    with app.app_context():
        app.logger.debug("Creating models")
        create_all()
        app.logger.debug(f"Created {len(db.metadata.tables)} tables")

    api = Api(app)
    initialize_routes(api)

    from flask_apscheduler import APScheduler
    scheduler = APScheduler()
    scheduler.api_enabled = True
    scheduler.init_app(app)

    @scheduler.task('interval', id='save_tasks_progres_from_redis_job', minutes=2)
    def save_tasks_progres_from_redis_job():
        """
        Save tasks updates that are enqueued to redis queue "task_updates".
        Main goal of this job is to process batched updates in database
        and reduce load of POST /tasks endpoint.
        """
        from datetime import datetime
        import json
        logging.info("SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS")
        from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, fetch_task_by_sim_id_and_task_id, update_tasks_states
        from yaptide.redis.redis import get_redis_client
        redis_client = get_redis_client()
        # Pop 1000 or less messages from left end of queue.
        messages = redis_client.lpop('task_updates', count = 1000)
        # Queue can be empty if there are no tasks to update
        if messages == None or len(messages) == 0:
            logging.info('No tasks received from redis')
            return
        
        start = datetime.now()
        
        # Deserialize all received task updates messages
        payload_dicts: list[dict] = [json.loads(message) for message in messages]
        tasks_to_update = []
        # Required to process data from oldest to newest - to prevent overriding new state by old for one task
        payload_dicts.reverse()
        with app.app_context():
            for payload_dict in payload_dicts:
                sim_id = payload_dict["simulation_id"]
                task_id = payload_dict["task_id"]
                task = fetch_task_by_sim_id_and_task_id(sim_id = sim_id, task_id = task_id)
                if not task:
                    logging.warning(f"Simulation {sim_id}: task {payload_dict['task_id']} does not exist")
                    continue
                tasks_to_update.append((task, payload_dict["update_dict"]))
            # Batch update of all accepted tasks
            update_tasks_states(tasks_to_update)
        finish = datetime.now()
        elapsed = (finish - start).total_seconds()
        logging.info(f"Tasks processed: {len(messages)}, tasks updated: {len(tasks_to_update)}, time elapsed: {elapsed}s")
        logging.info("Successfully updated tasks")
    
    
    scheduler._scheduler.start()

    return app


if __name__ == "__main__":
    create_app()
