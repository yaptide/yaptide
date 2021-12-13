from flask_restful import Resource

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response


class UserSimulations(Resource):
    """Class responsible for returning ids of user's task which are running simulations"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning ids"""
        simulations = db.session.query(SimulationModel).filter_by(user_id=user.id).all()

        result = {
            'simulations': [{
                'name': simulation.name,
                'task_id': simulation.task_id,
                'creation_date': simulation.creation_date,
            } for simulation in simulations]
        }
        return yaptide_response(message='User Simulations', code=200, content=result)
