from flask import request
from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import SimulationModel, TaskModel

from yaptide.routes.utils.response_templates import yaptide_response


class Results(Resource):
    """Class responsible for managing results"""

    @staticmethod
    def post():
        """
        
        """
