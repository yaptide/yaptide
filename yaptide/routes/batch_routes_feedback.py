from flask import request
from flask_restful import Resource
from yaptide.routes.utils.response_templates import yaptide_response


class BatchFeedback(Resource):

    def post():
        payload_dict: dict = request.get_json(force=True)
        if not payload_dict:
            return yaptide_response(message="No JSON in body", code=400)

        # todo
        # add job_dir, array_id, collect_id to simulation
