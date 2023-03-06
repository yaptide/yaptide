from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from enum import Enum

import math

from sqlalchemy import desc

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel, ClusterModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 10
DEFAULT_PAGE_IDX = 0


class OrderType(Enum):
    """Order type"""

    ASCEND = "ascend"
    DESCEND = "descend"


class OrderBy(Enum):
    """Order by column"""

    START_TIME = "start_time"
    END_TIME = "end_time"


class UserSimulations(Resource):
    """Class responsible for returning user's simulations' basic infos"""

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        page_size = fields.Integer(load_default=DEFAULT_PAGE_SIZE)
        page_idx = fields.Integer(load_default=DEFAULT_PAGE_IDX)
        order_by = fields.String(load_default=OrderBy.START_TIME.value)
        order_type = fields.String(load_default=OrderType.DESCEND.value)

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning simulations"""
        schema = UserSimulations._ParamsSchema()
        params_dict: dict = schema.load(request.args)

        if params_dict['order_by'] == OrderBy.END_TIME.value:
            if params_dict['order_type'] == OrderType.DESCEND.value:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).\
                    filter_by(user_id=user.id).order_by(desc(SimulationModel.end_time)).all()
            else:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).\
                    filter_by(user_id=user.id).order_by(SimulationModel.end_time).all()
        else:
            if params_dict['order_type'] == OrderType.DESCEND.value:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).\
                    filter_by(user_id=user.id).order_by(desc(SimulationModel.start_time)).all()
            else:
                simulations: list[SimulationModel] = db.session.query(SimulationModel).\
                    filter_by(user_id=user.id).order_by(SimulationModel.start_time).all()

        sim_count = len(simulations)
        page_size = (
            params_dict['page_size']
            if params_dict['page_size'] > 0 and params_dict['page_size'] < MAX_PAGE_SIZE
            else DEFAULT_PAGE_SIZE
        )
        page_count = int(math.ceil(sim_count/page_size))
        page_idx = (
            params_dict['page_idx']
            if params_dict['page_idx'] > -1 and params_dict['page_idx'] < page_count
            else DEFAULT_PAGE_IDX
        )
        simulations = simulations[page_size*page_idx: min(page_size*(page_idx+1), sim_count)]

        result = {
            'simulations': [
                {
                    'title': simulation.title,
                    'job_id': simulation.job_id,
                    'start_time': simulation.start_time,
                    'end_time': simulation.end_time,
                    'metadata': {
                        'platform': simulation.platform,
                        'server': 'Yaptide'
                    }
                }
                for simulation in simulations],
            'page_count': page_count,
            'simulations_count': sim_count,
        }
        return yaptide_response(message='User Simulations', code=200, content=result)


class UserClusters(Resource):
    """Class responsible for returning user's available clusters"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning clusters"""
        clusters: list[ClusterModel] = db.session.query(ClusterModel).filter_by(user_id=user.id).all()

        result = {
            'clusters': [
                {
                    'cluster_name': cluster.cluster_name
                }
                for cluster in clusters
            ]
        }
        return yaptide_response(message='User clusters', code=200, content=result)


class UserUpdate(Resource):
    """Class responsible for updating the user"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Updates user with provided parameters"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return error_validation_response()
        if 'grid_proxy' in json_data:
            user.grid_proxy = json_data['grid_proxy']
        db.session.commit()
        return yaptide_response(message='User updated', code=202)
