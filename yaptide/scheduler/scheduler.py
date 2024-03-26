from flask_apscheduler import APScheduler
from yaptide.scheduler.scheduler_tasks import save_tasks_progres_from_redis_job

# Single instance of FlaskAPScheduler shared by application and jobs
scheduler = APScheduler()

def run_scheduler(app):
    scheduler.init_app(app)
    scheduler.start()
    with app.app_context():
        scheduler.add_job(
            id="save_tasks_progres_from_redis",
            func = save_tasks_progres_from_redis_job,
            trigger="interval",
            seconds=2,
            args=(scheduler.app,))