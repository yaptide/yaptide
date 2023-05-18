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

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        page_size = fields.Integer(load_default=DEFAULT_PAGE_SIZE)
        page_idx = fields.Integer(load_default=DEFAULT_PAGE_IDX)
        order_by = fields.String(load_default=OrderBy.START_TIME.value)
        order_type = fields.String(load_default=OrderType.DESCEND.value)

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning simulations from the database"""
        schema = UserSimulations.APIParametersSchema()
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
                    # submission time, when user send the request to the backend, all jobs may start much later than that
                    'end_time': simulation.end_time,
                    # end time, when the all jobs are finished and results are merged
                    'metadata': {
                        'platform': simulation.platform,
                        'server': 'Yaptide',
                        'input_type': simulation.input_type,
                        'sim_type': simulation.sim_type
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
        return yaptide_response(message=f'User {user.username} updated', code=202)
