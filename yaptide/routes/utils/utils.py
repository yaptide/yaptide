from yaptide.persistence.db_methods import fetch_simulation_by_job_id
from yaptide.persistence.models import UserModel


def check_if_job_is_owned_and_exist(job_id: str, user: UserModel) -> tuple[bool, str, int]:
    """Function checking if provided task is owned by user managing action"""
    simulation = fetch_simulation_by_job_id(job_id=job_id)

    if not simulation:
        return False, 'Job with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Job with provided ID does not belong to the user', 403
