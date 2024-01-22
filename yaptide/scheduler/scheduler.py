from flask_apscheduler import APScheduler

# Single instance of FlaskAPScheduler shared by application and jobs
scheduler = APScheduler()