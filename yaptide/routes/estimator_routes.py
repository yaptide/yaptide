from flask import request
from flask_restful import Resource
from marshmallow import Schema, fields

from yaptide.persistence.db_methods import (fetch_estimator_names_by_job_id)
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
        """Method returning estimator names for specific simulation"""
        schema = EstimatorResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict['job_id']

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        estimator_names = fetch_estimator_names_by_job_id(job_id=job_id)

        if not estimator_names:
            return yaptide_response(message="Estimators not found", code=404)

        return yaptide_response(message="List of estimator names for specific simulation",
                                code=200,
                                content={"estimator_names": estimator_names})
