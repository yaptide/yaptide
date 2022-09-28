from flask import request
from flask_restful import Resource

from enum import Enum

from marshmallow import Schema
from marshmallow import fields

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response


class UserSimulations(Resource):
    """Class responsible for returning ids of user's task which are running simulations"""

    class OrderBy(Enum):
        START_TIME = "start_time"
        END_TIME = "end_time"


    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        page_size = fields.Integer(missing=10)
        page_idx = fields.Integer(missing=0)
        order_by = fields.String(missing="start_time")


    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning ids"""
        schema = UserSimulations._ParamsSchema()
        params_dict: dict = schema.load(request.args)

        simulations: list[SimulationModel] = db.session.query(SimulationModel).filter_by(user_id=user.id).all()

        def sort_func(sim: SimulationModel):
            if params_dict['order_by'] == UserSimulations.OrderBy.END_TIME.value:
                return sim.end_time
            return sim.start_time

        simulations.sort(key=sort_func)
        page_size = params_dict['page_size']
        page_idx = params_dict['page_idx']

        simulations = simulations[page_size*page_idx:min(page_size*(page_idx+1),len(simulations)-1)]

        result = {
            'simulations': [{
                'name': simulation.name,
                'task_id': simulation.task_id,
                'start_time': simulation.start_time,
                'end_time': simulation.end_time
            } for simulation in simulations]
        }
        return yaptide_response(message='User Simulations', code=200, content=result)
