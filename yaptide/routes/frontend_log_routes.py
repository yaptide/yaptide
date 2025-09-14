from flask_restful import Resource
from flask import request
import logging

from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.persistence.models import FrontendLogModel, UserModel
from yaptide.persistence.database import db
from yaptide.routes.utils.decorators import requires_auth


class FrontendLogs(Resource):
    """Receives logs from the frontend and saves them to the database"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Method saving frontend logs to database and returning status"""
        logging.debug("POST /logs received for user: %s", user.username)
        payload_dict: dict = request.get_json(force=True)
        if 'logs' not in payload_dict:
            return yaptide_response(message="Missing 'logs' key in JSON payload", code=400)

        logs = payload_dict['logs']
        required_keys = {"level", "message", "browser"}
        for entry in logs:

            # Valid log entries will be added to the sessions,
            # but commit won't happen unless all entries are valid
            # maybe add db.session.commit(), but then what should be the response?
            if not required_keys.issubset(entry.keys()):
                diff = required_keys.difference(entry.keys())
                return yaptide_response(message=f"Missing keys in logs payload: {diff}", code=400)

            # Sanitize message and browser to fit database model
            # and prevent overflows
            message = entry.get('message').strip()
            if len(message) > 2048:
                message = message[:2045] + '...'

            browser = entry.get('browser').strip()
            if len(browser) > 256:
                browser = browser[:253] + '...'

            timestamp = entry.get('timestamp')
            log = FrontendLogModel(user_id=user.id, level=entry.get('level'), message=message, browser=browser)

            # If timestamp is provided, use it; otherwise, the default server time will be used
            if timestamp:
                log.timestamp = timestamp
            db.session.add(log)

        db.session.commit()
        return yaptide_response(message='Logs received', code=200)
