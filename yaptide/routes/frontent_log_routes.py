from flask_restful import Resource
from flask import request

from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.persistence.models import FrontendLogModel, UserModel
from yaptide.persistence.database import db
from yaptide.routes.utils.decorators import requires_auth


class FrontendLogs(Resource):
    """Receives logs from the forntent and saves them to the database"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Method saving frontend logs to database and returning status"""
        print("POST /logs received")
        json_data = request.get_json(force=True)

        logs = json_data['logs']

        for entry in logs:
            log = FrontendLogModel(
                user_id=user.id,
                timestamp=entry['timestamp'],
                level=entry['level'],
                message=entry['message'],
                browser=entry['browser'],
                user_ip=entry['user_ip'],
            )
            db.session.add(log)

        db.session.commit()
        return yaptide_response(message='Logs received', code=200)
