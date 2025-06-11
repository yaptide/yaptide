from typing import Optional

from yaptide.persistence.db_methods import fetch_simulation_by_job_id
from yaptide.persistence.models import UserModel
from yaptide.utils.enums import InputType
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries


def check_if_job_is_owned_and_exist(job_id: str, user: UserModel) -> tuple[bool, str, int]:
    """Function checking if provided task is owned by user managing action"""
    simulation = fetch_simulation_by_job_id(job_id=job_id)

    if not simulation:
        return False, 'Job with provided ID does not exist', 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, 'Job with provided ID does not belong to the user', 403


def determine_input_type(payload_dict: dict) -> Optional[str]:
    """Function returning input type determined from payload"""
    if payload_dict["input_type"] == "editor":
        if "input_json" not in payload_dict:
            return None
        return InputType.EDITOR.value
    if payload_dict["input_type"] == "files":
        if "input_files" not in payload_dict:
            return None
        return InputType.FILES.value
    return None


def make_input_dict(payload_dict: dict, input_type: str) -> dict:
    """Function returning input dict"""
    input_dict = {
        "input_type": input_type,
    }
    if input_type == InputType.EDITOR.value:
        files_dict, number_of_all_primaries = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
        input_dict["input_json"] = payload_dict["input_json"]
    else:
        files_dict, number_of_all_primaries = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
    input_dict["number_of_all_primaries"] = number_of_all_primaries
    input_dict["number_of_requested_primaries"] = number_of_all_primaries
    input_dict["input_files"] = files_dict

    return input_dict
