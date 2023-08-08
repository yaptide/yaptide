import logging
from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from enum import Enum

from sqlalchemy import asc, desc

from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

DEFAULT_PAGE_SIZE = 6  # default number of simulations per page
DEFAULT_PAGE_IDX = 1  # default page index


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
    @requires_auth()
    def get(user: UserModel):
        """Method returning simulations from the database"""
        schema = UserSimulations.APIParametersSchema()
        params_dict: dict = schema.load(request.args)
        logging.info('User %s requested simulations with parameters: %s', user.username, params_dict)

        # Query the database for the paginated results
        sorting = desc if params_dict['order_type'] == OrderType.DESCEND.value else asc
        query = SimulationModel.query.\
            filter(SimulationModel.job_id != None).\
            filter_by(user_id=user.id).\
            order_by(sorting(params_dict['order_by']))
        pagination = query.paginate(page=params_dict['page_idx'], per_page=params_dict['page_size'], error_out=False)
        simulations = pagination.items

        result = {
            'simulations': [
                {
                    'title': simulation.title,
                    'job_id': simulation.job_id,
                    'start_time': simulation.start_time,
                    # submission time, when user send the request to the backend - jobs may start much later than that
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
            'page_count': pagination.pages,
            'simulations_count': pagination.total,
        }
        return yaptide_response(message='User Simulations', code=200, content=result)


class UserUpdate(Resource):
    """Class responsible for updating the user"""

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Updates user with provided parameters"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return error_validation_response()
        return yaptide_response(message=f'User {user.username} updated', code=202)
