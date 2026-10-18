from datetime import datetime, timezone
from typing import Optional
import logging

from environs import env, EnvValidationError

from yaptide.persistence.database import db
from yaptide.persistence.db_methods import (
    fetch_simulation_by_job_id,
    fetch_task_summary,
    fetch_tasks_by_sim_id,
)
from yaptide.persistence.models import (
    BatchSimulationModel,
    ClusterModel,
    SimulationModel,
    UserModel,
    YaptideUserModel,
)
from yaptide.utils.enums import EntityState, InputType, PlatformType
from yaptide.utils.sim_utils import files_dict_with_adjusted_primaries, get_total_number_of_primaries


def local_users_enabled() -> bool:
    """Whether local (username/password) users can register, log in and use the service.

    Local users are enabled only when the ENABLE_LOCAL_USERS environment variable is set to
    a truthy value (true/1/yes/on). When it is unset, the instance accepts Keycloak users only.
    An invalid value is logged and treated as disabled.
    """
    try:
        return env.bool("ENABLE_LOCAL_USERS", False)
    except EnvValidationError as e:
        logging.error("Local users disabled due to invalid ENABLE_LOCAL_USERS: %s", e)
        return False


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


FINAL_STATES = (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value)
# the order states follow; FAILED can come at any point before the end
PROGRESSION = [
    EntityState.UNKNOWN.value,
    EntityState.PENDING.value,
    EntityState.RUNNING.value,
    EntityState.MERGING_QUEUED.value,
    EntityState.MERGING_RUNNING.value,
    EntityState.FAILED.value,
]


def job_status_content(simulation: SimulationModel, with_tasks: bool, summary: Optional[dict] = None) -> dict:
    """Simulation status as the UI polls it: totals over the tasks always (counted here unless given), the list of
    tasks only when asked for
    """
    content = {"job_state": simulation.job_state, "job_tasks_summary": summary or fetch_task_summary(simulation.id)}
    if simulation.partial_primaries is not None:
        # the stored results cover only these primaries: the simulation has not finished
        content["partial_results"] = {
            "simulated_primaries": simulation.partial_primaries,
            # SQLite drops the time zone of the UTC time stored
            "time": simulation.partial_time.replace(tzinfo=simulation.partial_time.tzinfo or timezone.utc).isoformat(),
        }
    cluster = busy_cluster(simulation)
    if cluster:
        # it waits for its cluster, which the engine tries again then
        busy_until = cluster.busy_until
        content["cluster_busy_until"] = busy_until.replace(tzinfo=busy_until.tzinfo or timezone.utc).isoformat()
        if cluster.notice:
            # e.g. its admins closed the logins: what they said about it
            content["cluster_notice"] = cluster.notice
    if with_tasks:
        content["job_tasks_status"] = [task.get_status_dict() for task in fetch_tasks_by_sim_id(sim_id=simulation.id)]
    return content


def busy_cluster(simulation: SimulationModel) -> Optional[ClusterModel]:
    """The cluster of an HPC simulation still to be submitted, while its SLURM does not answer (the engine tries it
    again at busy_until); None otherwise
    """
    if not isinstance(simulation, BatchSimulationModel):
        return None
    if simulation.job_state != EntityState.PENDING.value or simulation.array_id is not None:
        return None
    cluster = db.session.get(ClusterModel, simulation.cluster_id)
    return cluster if cluster and cluster.busy_until else None


def update_state_from_tasks(simulation: SimulationModel, states_changed: bool = True) -> None:
    """Tells that the tasks of a simulation saved their progress: counts the save in progress_revision and, when a
    task's state changed, moves the simulation forward - RUNNING once a task runs, FAILED when all failed and, for
    HPC simulations, MERGING_QUEUED once all ended (the collect job reports the rest); the engine merges direct
    simulations itself. A state never moves back, and a final one is kept. One transaction, so the streams of the
    simulation get one event for the save.
    """
    if states_changed:
        state_update = state_update_from_tasks(simulation)
        if state_update:
            update, earlier = state_update
            # one conditional statement: a cancel or result stored meanwhile by another request is not overwritten
            db.session.query(SimulationModel).filter(
                SimulationModel.id == simulation.id, SimulationModel.job_state.in_(earlier)
            ).update(update, synchronize_session=False)
    # the streams follow a simulation only until it ends
    db.session.query(SimulationModel).filter(
        SimulationModel.id == simulation.id, SimulationModel.job_state.notin_(FINAL_STATES)
    ).update({SimulationModel.progress_revision: SimulationModel.progress_revision + 1}, synchronize_session=False)
    db.session.commit()


def state_update_from_tasks(simulation: SimulationModel) -> Optional[tuple[dict, list[str]]]:
    """The state the tasks move the simulation to, with the states it may move from; None when they move nothing"""
    summary = fetch_task_summary(simulation.id)
    states, ntasks = summary["task_states"], summary["ntasks"]
    ended = sum(states.get(state, 0) for state in FINAL_STATES)
    if states.get(EntityState.FAILED.value) == ntasks:
        job_state, before = EntityState.FAILED.value, EntityState.FAILED.value
    elif ended == ntasks and simulation.platform == PlatformType.BATCH.value:
        job_state, before = EntityState.MERGING_QUEUED.value, EntityState.MERGING_QUEUED.value
    elif states.get(EntityState.RUNNING.value) or ended:
        job_state, before = EntityState.RUNNING.value, EntityState.RUNNING.value
    else:
        return None
    # the states it may move from: only earlier ones, and never a final one
    earlier = [state for state in PROGRESSION[: PROGRESSION.index(before)] if state not in FINAL_STATES]
    if simulation.job_state not in earlier:
        return None
    update = {SimulationModel.job_state: job_state}
    if job_state == EntityState.FAILED.value:
        update[SimulationModel.end_time] = datetime.utcnow()
    return update, earlier


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
