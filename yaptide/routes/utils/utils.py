from typing import Optional
import logging
import os

from yaptide.persistence.db_methods import fetch_simulation_by_job_id
from yaptide.persistence.models import UserModel, YaptideUserModel
from yaptide.utils.enums import InputType
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries, get_total_number_of_primaries


def _env_flag(name: str, default: bool = True) -> bool:
    """Read a boolean flag from the environment; falsy values are false/0/no/off/empty"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"false", "0", "no", "off", ""}


def local_users_enabled() -> bool:
    """Whether local (username/password) users can register, log in and use the service.

    On deployments that rely solely on Keycloak for authentication (e.g. yap-dev and yaptide)
    local users can be switched off completely by setting the ENABLE_LOCAL_USERS environment
    variable to a falsy value. When the variable is unset, local users stay enabled
    to preserve the behaviour for local development and tests.
    """
    return _env_flag("ENABLE_LOCAL_USERS")


def registration_enabled() -> bool:
    """Whether local user registration via the /auth/register endpoint is enabled.

    Registration can be switched off on its own by setting the ENABLE_USER_REGISTRATION
    environment variable to a falsy value, while still allowing existing local users to log in.
    It is always disabled when local users are disabled (see local_users_enabled).
    """
    return local_users_enabled() and _env_flag("ENABLE_USER_REGISTRATION")


def is_disabled_local_user(user: UserModel) -> bool:
    """Whether the user is a local user while local users are disabled on this instance"""
    return isinstance(user, YaptideUserModel) and not local_users_enabled()


def check_if_job_is_owned_and_exist(job_id: str, user: UserModel) -> tuple[bool, str, int]:
    """Function checking if provided task is owned by user managing action"""
    simulation = fetch_simulation_by_job_id(job_id=job_id)

    if not simulation:
        return False, "Job with provided ID does not exist", 404
    if simulation.user_id == user.id:
        return True, "", 200
    return False, "Job with provided ID does not belong to the user", 403


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


def get_clamped_ntasks_value(payload_dict: dict, ntasks: int) -> int:
    """
    Function that validates ntasks value in a simulation and returns the number of tasks that the simulation should use.
    It's used to prevent simulations with ntasks outside of range [1; primaries_count].
    The ntasks value needs to be larger than 0, because you need at least a single task to run a simulation
    with certain simulators (like SHIELD-HIT12A).
    The ntasks value also needs to be less than or equal to the number of primaries, because a task
    needs at least one primary to run. If the number of tasks is larger than the number of primaries
    then some tasks would have 0 primaries in them, which will make the simulation crash.

    Args:
        payload_dict: A dictionary containing the payload received from a request.
        ntasks: Task count from the request to be clamped

    Returns:
        Integer value representing the ntasks value to use in the simulation.
    """
    # ensure there is at least 1 task
    if ntasks < 1:
        logging.warning("Received %d as the ntasks value. The value shouldn't be less than 1. Clamping to 1.", ntasks)
        return 1

    # get the total number of primaries for the whole simulation/job
    number_of_all_primaries = get_total_number_of_primaries(payload_dict)

    # if we couldn't get the total number of primaries, fall back to the original ntasks value
    if number_of_all_primaries is None:
        logging.warning(
            "Could not determine the total number of primaries from the payload.\
                         Therefore we cannot validate the ntasks value. Using the received value without validation."
        )
        return ntasks

    # if number of all primaries is less than 1, fall back to 1 task
    # if this happens the simulation will most likely fail anyway, but it's better to check it,
    # because it could just be incorrect read from the function above or something similar
    if number_of_all_primaries < 1:
        return 1

    # if the number of tasks is larger than the number of primaries, clamp the number of tasks to its value
    if ntasks > number_of_all_primaries:
        logging.warning(
            "The received ntasks value is %d and the determined number of all primaries is %d.\
                         To avoid simulation crashing by having tasks with 0 primaries, the number of tasks\
                         should be less than or equal to the number of all primaries.\
                         Clamping ntasks value to the number of all primaries.",
            ntasks,
            number_of_all_primaries,
        )
        return number_of_all_primaries

    # if ntasks is within range, return the original value
    return ntasks
