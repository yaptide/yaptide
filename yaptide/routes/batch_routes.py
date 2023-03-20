from flask import request
from flask_restful import Resource

from marshmallow import Schema
from marshmallow import fields

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_validation_response

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel, ClusterModel

from yaptide.batch.batch_methods import submit_job, get_job, delete_job


class JobsBatch(Resource):
    """Class responsible for jobs via direct slurm connection"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with batch"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in json_data:
            return error_validation_response()

        clusters: list[ClusterModel] = db.session.query(ClusterModel).filter_by(user_id=user.id).all()
        if len(clusters) < 1:
            return error_validation_response({"message": "User has no clusters available"})

        filtered_clusters: list[ClusterModel] = []
        if "batch_options" in json_data and "cluster_name" in json_data["batch_options"]:
            cluster_name = json_data["batch_options"]["cluster_name"]
            filtered_clusters = [cluster for cluster in clusters if cluster.cluster_name == cluster_name]
        cluster = filtered_clusters[0] if len(filtered_clusters) > 0 else clusters[0]

        sim_type = SimulationModel.SimType.SHIELDHIT.value if "sim_type" not in json_data or\
            json_data["sim_type"].upper() == SimulationModel.SimType.SHIELDHIT.value else\
            SimulationModel.SimType.DUMMY.value

        input_type = SimulationModel.InputType.YAPTIDE_PROJECT.value if\
            "metadata" in json_data["sim_data"] else\
            SimulationModel.InputType.INPUT_FILES.value

        result, status_code = submit_job(json_data=json_data, cluster=cluster)

        if "job_id" in result:
            simulation = SimulationModel(
                job_id=result["job_id"],
                user_id=user.id,
                platform=SimulationModel.Platform.BATCH.value,
                sim_type=sim_type,
                input_type=input_type
            )
            if "title" in json_data:
                simulation.set_title(json_data["title"])

            db.session.add(simulation)
            db.session.commit()

        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    class _ParamsSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(load_default="None")

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method geting job's result"""
        schema = JobsBatch._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=params_dict["job_id"], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation: SimulationModel = db.session.query(SimulationModel).\
            filter_by(job_id=params_dict["job_id"]).first()
        splitted_job_id: list[str] = params_dict["job_id"].split(":")
        job_id, cluster_name = splitted_job_id[0], splitted_job_id[1]
        cluster: ClusterModel = db.session.query(ClusterModel).\
            filter_by(user_id=user.id, cluster_name=cluster_name).first()
        json_data = {
            "job_id": job_id,
            "start_time_for_dummy": simulation.start_time,
            "end_time_for_dummy": simulation.end_time
        }

        result, status_code = get_job(json_data=json_data, cluster=cluster)

        if "end_time" in result and simulation.end_time is None:
            simulation.end_time = result['end_time']
            db.session.commit()

        result.pop("end_time", None)

        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling job"""
        schema = JobsBatch._ParamsSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return error_validation_response(content=errors)
        params_dict: dict = schema.load(request.args)

        is_owned, error_message, res_code = check_if_job_is_owned(job_id=params_dict["job_id"], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        splitted_job_id: list[str] = params_dict["job_id"].split(":")
        job_id, cluster_name = splitted_job_id[0], splitted_job_id[1]
        cluster: ClusterModel = db.session.query(ClusterModel).\
            filter_by(user_id=user.id, cluster_name=cluster_name).first()
        json_data = {
            "job_id": job_id
        }
        result, status_code = delete_job(json_data=json_data, cluster=cluster)
        return yaptide_response(
            message="",
            code=status_code,
            content=result
        )


def check_if_job_is_owned(job_id: str, user: UserModel) -> tuple[bool, str]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

    if not simulation:
        return False, 'Task with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Task with provided ID does not belong to the user', 403
