import logging
from enum import Enum

from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields
from sqlalchemy import asc, desc

from yaptide.persistence.models import SimulationModel, UserModel
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import (error_validation_response, yaptide_response)
from yaptide.persistence.db_methods import (delete_object_from_db, fetch_simulation_by_job_id)
from yaptide.utils.enums import EntityState

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
        job_id = fields.String()

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
                } for simulation in simulations
            ],
            'page_count':
            pagination.pages,
            'simulations_count':
            pagination.total,
        }
        return yaptide_response(message='User Simulations', code=200, content=result)

    @staticmethod
    @requires_auth()
    def delete(user: UserModel):
        """Method deleting simulation from database"""
        schema = UserSimulations.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        job_id = params_dict['job_id']
        simulation = fetch_simulation_by_job_id(job_id)

        if simulation is None:
            return yaptide_response(message=f'Simulation with job_id={job_id} do not exist', code=404)

        # Simulation has to be completed/cancelled before deleting it.
        if simulation.job_state in (EntityState.UNKNOWN.value, EntityState.PENDING.value, EntityState.RUNNING.value):
            return yaptide_response(message=f'''Simulation with job_id={job_id} is currently running.
                  Please cancel simulation or wait for it to finish''',
                                    code=403)

        delete_object_from_db(simulation)
        return yaptide_response(message=f'Simulation with job_id={job_id} successfully deleted from database', code=200)


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
