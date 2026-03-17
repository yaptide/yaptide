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
    input_dict["input_files"] = files_dict

    return input_dict


def get_clumped_ntasks_value(payload_dict: dict, input_type: str) -> int:
    """
    Function that validates ntasks value in a simulation and returns the number of tasks that the simulation should use.
    It's used to prevents simulations with ntasks outside of range [1; primaries_count].
    The ntasks value needs to be larger than 0, because you need at least a single task to run a simulation.
    The ntasks value also needs to be smaller than the number of primaries, because a task
    needs at least one primary to run. If the number of tasks is larger than the number of primaries
    then some tasks would have 0 primaries in them, which will make the simulation crash.

    Args:
        payload_dict: A dictionary containing the payload received from a request.
        input_type: Input type determining if the request used editor or files.

    Returns:
        Integer value representing the ntasks value to use in the simulation.
    """
    # ensure there is at least 1 task
    if payload_dict["ntasks"] < 1:
        return 1

    # get the number of primaries, depending on the input_type
    if input_type == InputType.EDITOR.value:
        number_of_all_primaries = payload_dict["input_json"]["beam"]["numberOfParticles"]
    # ugly way of determining the file type, but that's how it's done in sim_utils
    elif 'beam.dat' in payload_dict["input_files"]:
        all_beam_lines: list[str] = payload_dict["input_files"]['beam.dat'].split('\n')
        all_beam_lines_with_nstat = [line for line in all_beam_lines if line.lstrip().startswith('NSTAT')]
        number_of_all_primaries = int(all_beam_lines_with_nstat[0].split()[1])
    elif next((file for file in payload_dict["input_files"] if file.endswith(".inp")), None):
        input_file = next((file for file in payload_dict["input_files"] if file.endswith(".inp")), None)
        # read number of primaries from fluka file
        all_input_lines: list[str] = payload_dict["input_files"][input_file].split('\n')
        # get value from START card
        start_card = next((line for line in all_input_lines if line.lstrip().startswith('START')), None)
        number_of_all_primaries = int(float(start_card.split()[1]))
    # if we cannot determine the file type, fallback to original ntasks
    else:
        return payload_dict["ntasks"]

    # if the number of tasks is larger than the number of primaries, clump the number of tasks to its value
    if payload_dict["ntasks"] > number_of_all_primaries:
        return number_of_all_primaries

    # if ntasks is within range, return the original value
    return payload_dict["ntasks"]

