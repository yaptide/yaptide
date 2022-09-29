from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from enum import Enum

import math

from sqlalchemy import desc

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response


class UserSimulations(Resource):
    """Class responsible for returning ids of user's task which are running simulations"""

    class OrderType(Enum):
        """Order type"""

        ASCEND = "ascend"
        DESCEND = "descend"

    class OrderBy(Enum):
        """Order by column"""

        START_TIME = "start_time"
        END_TIME = "end_time"

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        page_size = fields.Integer(missing=10)
        page_idx = fields.Integer(missing=0)
        order_by = fields.String(missing="start_time")
        order_type = fields.String(missing="ascend")

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning ids"""
        schema = UserSimulations._ParamsSchema()
        params_dict: dict = schema.load(request.args)

        if params_dict['order_by'] == UserSimulations.OrderBy.END_TIME.value:
            if params_dict['order_type'] == UserSimulations.OrderType.DESCEND.value:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).filter_by(
                    user_id=user.id).order_by(desc(SimulationModel.end_time)).all()
            else:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).filter_by(
                    user_id=user.id).order_by(SimulationModel.end_time).all()
        else:
            if params_dict['order_type'] == UserSimulations.OrderType.DESCEND.value:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).filter_by(
                    user_id=user.id).order_by(desc(SimulationModel.start_time)).all()
            else:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).filter_by(
                    user_id=user.id).order_by(SimulationModel.start_time).all()

        sim_count = len(simulations)
        page_size = params_dict['page_size']
        page_idx = params_dict['page_idx']
        page_count = int(math.ceil(sim_count/page_size))
        simulations = simulations[page_size*page_idx: min(page_size*(page_idx+1),sim_count)]

        result = {
            'simulations': [{
                'name': simulation.name,
                'task_id': simulation.task_id,
                'start_time': simulation.start_time,
                'end_time': simulation.end_time
            } for simulation in simulations],
            'page_count': page_count
        }
        return yaptide_response(message='User Simulations', code=200, content=result)
