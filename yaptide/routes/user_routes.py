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
            'tasks_ids': [simulation.task_id for simulation in simulations]
        }
        # if len(simulations) > 0:
        #     for simulation in simulations:
        #         result['tasks_ids'].append(simulation.task_id)
        return yaptide_response(message='User Simulations', code=200, content=result)
