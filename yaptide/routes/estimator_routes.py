from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.persistence.db_methods import (fetch_estimators_by_sim_id, fetch_pages_metadata_by_est_id,
                                            fetch_simulation_id_by_job_id)
from yaptide.persistence.models import (UserModel)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist


class EstimatorResource(Resource):
    """Class responsible for retreving estimator names"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning estimators metadata for specific simulation"""
        schema = EstimatorResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation_id = fetch_simulation_id_by_job_id(job_id=job_id)
        if not simulation_id:
            return yaptide_response(message="Simulation does not exist", code=404)

        estimators = fetch_estimators_by_sim_id(sim_id=simulation_id)
        results = []

        for estimator in estimators:
            pages_metadata = fetch_pages_metadata_by_est_id(est_id=estimator.id)
            estimator_dict = {
                "name":
                estimator.name,
                "pages_metadata": [{
                    "page_number": page[0],
                    "page_name": page[1],
                    "page_dimension": page[2]
                } for page in pages_metadata]
            }
            results.append(estimator_dict)

        if len(results) == 0:
            return yaptide_response(message="Pages metadata not found", code=404)

        return yaptide_response(message="Estimators metadata", code=200, content={"estimators_metadata": results})
