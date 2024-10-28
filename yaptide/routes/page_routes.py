from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.persistence.db_methods import (fetch_pages_metadata_by_sim_id_and_est_name, fetch_simulation_by_job_id)
from yaptide.persistence.models import UserModel
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist


class PagesResource(Resource):
    """Class responsible for retrieving pages metadata"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()
        estimator_name = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning job status and results.
        If `estimator_name` parameter is provided,
        the response will include results only for that specific estimator,
        otherwise it will return all estimators for the given job.
        """
        schema = PagesResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']
        estimator_name = param_dict['estimator_name']

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        pages_metadata = fetch_pages_metadata_by_sim_id_and_est_name(sim_id=simulation.id, est_name=estimator_name)
        if not pages_metadata:
            return yaptide_response(message="Pages metadata not found", code=404)

        result = [{'page_number': page[0], 'page_dimension': page[1]} for page in pages_metadata]
        return yaptide_response(message=f"Pages metadata for estimator '{estimator_name}', simulation: {simulation.id}",
                                code=200,
                                content={"pages_metadata": result})
