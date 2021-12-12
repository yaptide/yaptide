from flask import request
from flask_restful import Resource

from marshmallow import Schema, ValidationError
from marshmallow import fields

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel

from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response, error_internal_response, error_validation_response

from yaptide.celery.tasks import run_simulation, simulation_task_status, get_input_files, cancel_simulation


class SimulationRun(Resource):
    """Class responsible for Shieldhit Demo running"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        jobs = fields.Integer(missing=1)
        sim_type = fields.String(missing="shieldhit")
        sim_name = fields.String(missing="")

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method handling running shieldhit with server"""
        schema = SimulationRun._Schema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        json_data: dict = request.get_json(force=True)
        if not json_data:
            return yaptide_response(message="No JSON in body", code=400)

        task = run_simulation.delay(param_dict=param_dict, raw_input_dict=json_data)

        if param_dict['sim_name'] == "":
            simulation = SimulationModel(task_id=task.id, user_id=user.id)
        else:
            simulation = SimulationModel(task_id=task.id, user_id=user.id, name=param_dict['sim_name'])

        db.session.add(simulation)
        db.session.commit()

        return yaptide_response(
            message="Task started",
            code=202,
            content={'task_id': task.id}
        )


def check_if_task_is_owned(task_id: str, user: UserModel) -> tuple[bool, str]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(
        SimulationModel).filter_by(task_id=task_id).first()

    if simulation.user_id == user.id:
        return True, ""
    return False, 'Task with provided ID does not belong to the user'


class SimulationStatus(Resource):
    """Class responsible for returning Shieldhit Demo status and result"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method returning task status and results"""
        try:
            json_data: dict = SimulationStatus._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=403)

        task = simulation_task_status.delay(task_id=json_data.get('task_id'))
        result: dict = task.wait(timeout=None, interval=0.5)

        content: dict = result.get('content')
        if result.get('status') == 'OK':
            return yaptide_response(
                message='Task state: {state}'.format(state=content['state']),
                code=200,
                content=content
            )
        return yaptide_response(
            message='Task failed',
            code=200,
            content=content
        )


class SimulationInputs(Resource):
    """Class responsible for returning converted simulation input files"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def post(user: UserModel):
        """Method returning simulation input files"""
        try:
            json_data: dict = SimulationInputs._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=403)

        task = get_input_files.delay(task_id=json_data.get('task_id'))
        result: dict = task.wait(timeout=None, interval=0.5)

        return yaptide_response(
            message=result['info'],
            code=200,
            content=result.get('content')
        )


class SimulationCancel(Resource):
    """Class responsible for canceling simulation"""

    class _Schema(Schema):
        """Class specifies API parameters"""

        task_id = fields.String()

    @staticmethod
    @requires_auth(is_refresh=False)
    def delete(user: UserModel):
        """Method canceling simulation and returning status of this action"""
        try:
            json_data: dict = SimulationCancel._Schema().load(request.get_json(force=True))
        except ValidationError:
            return error_validation_response()

        is_owned, error_message = check_if_task_is_owned(task_id=json_data.get('task_id'), user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=403)

        task = cancel_simulation.delay(task_id=json_data.get('task_id'))
        result: dict = task.wait(timeout=None, interval=0.5)

        if result:
            db.session.query(SimulationModel).filter_by(task_id=json_data.get('task_id')).delete()
            db.session.commit()

        return error_internal_response()
