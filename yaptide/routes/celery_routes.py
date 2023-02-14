from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from datetime import datetime

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

from yaptide.celery.tasks import (run_simulation, convert_input_files, simulation_task_status,
                                  get_input_files, cancel_simulation)


class JobsDirect(Resource):
    """Class responsible for SHIELD-HIT12A simulations running"""

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with server"""
        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        if "sim_data" not in json_data:
            return error_validation_response()

        task = run_simulation.delay(param_dict={
            "jobs": json_data["jobs"] if "jobs" in json_data else -1,
            "sim_type": json_data["sim_type"] if "sim_type" in json_data else "shieldhit",
            "sim_name": json_data["sim_name"] if "sim_name" in json_data else ""
        }, raw_input_dict=json_data["sim_data"])

        if json_data.get('sim_name'):
            simulation = SimulationModel(
                task_id=task.id, user_id=user.id, name=json_data['sim_name'],
                platform=SimulationModel.Platform.DIRECT.value)
        else:
            simulation = SimulationModel(
                task_id=task.id, user_id=user.id, platform=SimulationModel.Platform.DIRECT.value)

        db.session.add(simulation)
        db.session.commit()

        return yaptide_response(
            message="Task started",
            code=202,
            content={'task_id': task.id}
        )

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning task status and results"""
        schema = JobsDirect._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        task_id = param_dict['task_id']
        is_owned, error_message, res_code = check_if_task_is_owned(task_id=task_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        task = simulation_task_status.delay(task_id=task_id)
        result: dict = task.wait()
        simulation: SimulationModel = db.session.query(SimulationModel).filter_by(task_id=task_id).first()

        if "end_time" in result and "cores" in result and simulation.end_time is None and simulation.cores is None:
            simulation.end_time = datetime.strptime(result['end_time'], '%Y-%m-%dT%H:%M:%S.%f')
            simulation.cores = result['cores']
            db.session.commit()

        return yaptide_response(
            message=f"Task state: {result['state']}",
            code=200,
            content=result
        )

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        try:
            json_data: dict = JobsDirect._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message, res_code = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        task = cancel_simulation.delay(task_id=json_data.get('task_id'))
        result: dict = task.wait()

        if result:
            db.session.query(SimulationModel).filter_by(task_id=json_data.get('task_id')).delete()
            db.session.commit()

        return error_internal_response()


class ConvertInputFiles(Resource):
    """Class responsible for returning input files converted from front JSON"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        sim_type = fields.String(load_default="shieldhit")

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):  # skipcq: PYL-W0613
        """Method handling input files convertion"""
        schema = ConvertInputFiles._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        task = convert_input_files.delay(param_dict=param_dict, raw_input_dict=json_data)
        result: dict = task.wait()

        return yaptide_response(
            message="Converted Input Files",
            code=200,
            content=result
        )


def check_if_task_is_owned(task_id: str, user: UserModel) -> tuple[bool, str]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(task_id=task_id).first()

    if not simulation:
        return False, 'Task with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Task with provided ID does not belong to the user', 403


class SimulationInputs(Resource):
    """Class responsible for returning converted simulation input files"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def get(user: UserModel):
        """Method returning simulation input files"""
        schema = SimulationInputs._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)
        task_id = param_dict['task_id']

        is_owned, error_message, res_code = check_if_task_is_owned(task_id=task_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        task = get_input_files.delay(task_id=task_id)
        result: dict = task.wait()

        return yaptide_response(
            message=result['info'],
            code=200,
            content=result
        )
