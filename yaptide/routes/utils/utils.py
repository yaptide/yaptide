from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel


def check_if_job_is_owned_and_exist(job_id: str, user: UserModel) -> tuple[bool, str, int]:
    """Function checking if provided task is owned by user managing action"""
    simulation = db.session.query(SimulationModel).filter_by(job_id=job_id).first()

    if not simulation:
        return False, 'Job with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Job with provided ID does not belong to the user', 403
