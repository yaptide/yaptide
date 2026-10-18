import logging
import time
from datetime import datetime, timezone
from typing import Optional, Union

from sqlalchemy import DateTime, Integer, String, and_, bindparam, case, func, update
from sqlalchemy.exc import InterfaceError, InternalError, OperationalError
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import with_polymorphic

from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    BatchTaskModel,
    CelerySimulationModel,
    CeleryTaskModel,
    ClusterModel,
    EstimatorModel,
    InputModel,
    KeycloakUserModel,
    LogfilesModel,
    PageModel,
    SimulationModel,
    TaskModel,
    UserActivityModel,
    UserModel,
    YaptideUserModel,
)
from yaptide.utils.enums import EntityState


def add_object_to_db(obj: db.Model, make_commit: bool = True) -> None:
    """Adds object to database and makes commit"""
    db.session.add(obj)
    if make_commit:
        make_commit_to_db()


def delete_object_from_db(obj: db.Model, make_commit: bool = True) -> None:
    """Deletes object from database and makes commit"""
    db.session.delete(obj)
    if make_commit:
        make_commit_to_db()


def make_commit_to_db():
    """Makes commit"""
    db.session.commit()


def fetch_user_by_id(user_id: int) -> Union[KeycloakUserModel, YaptideUserModel]:
    """Fetches user by id"""
    UserPoly = with_polymorphic(UserModel, [YaptideUserModel, KeycloakUserModel])
    user = db.session.query(UserPoly).filter_by(id=user_id).first()
    return user


def fetch_yaptide_user_by_username(username: str) -> YaptideUserModel:
    """Fetches user by username"""
    user = db.session.query(YaptideUserModel).filter_by(username=username).first()
    return user


def fetch_keycloak_user_by_username(username: str) -> KeycloakUserModel:
    """Fetches user by username"""
    user = db.session.query(KeycloakUserModel).filter_by(username=username).first()
    return user


def fetch_simulation_by_job_id(job_id: str) -> Union[BatchSimulationModel, CelerySimulationModel]:
    """Fetches simulation by job id"""
    SimulationPoly = with_polymorphic(SimulationModel, [BatchSimulationModel, CelerySimulationModel])
    simulation = db.session.query(SimulationPoly).filter_by(job_id=job_id).first()
    return simulation


def fetch_simulation_id_by_job_id(job_id: str) -> Optional[int]:
    """Fetches simulation_id by job_id for both Celery and Batch simulations.
    Returns simulation_id if simulation exists,
    or None if no simulation is found.
    """
    simulation_id = db.session.query(SimulationModel.id).filter_by(job_id=job_id).first()
    return simulation_id[0] if simulation_id else None


def fetch_celery_simulation_by_job_id(job_id: str) -> CelerySimulationModel:
    """Fetches celery simulation by job id"""
    simulation = db.session.query(CelerySimulationModel).filter_by(job_id=job_id).first()
    return simulation


def fetch_batch_simulation_by_job_id(job_id: str) -> BatchSimulationModel:
    """Fetches batch simulation by job id"""
    simulation = db.session.query(BatchSimulationModel).filter_by(job_id=job_id).first()
    return simulation


def fetch_simulation_by_sim_id(sim_id: int) -> Union[BatchSimulationModel, CelerySimulationModel]:
    """Fetches simulation by sim id"""
    SimulationPoly = with_polymorphic(SimulationModel, [BatchSimulationModel, CelerySimulationModel])
    simulation = db.session.query(SimulationPoly).filter_by(id=sim_id).first()
    return simulation


def fetch_simulations_by_user_id(user_id: int) -> Union[list[BatchSimulationModel], list[CelerySimulationModel]]:
    """Fetches simulations by user id, sorted by id"""
    SimulationPoly = with_polymorphic(SimulationModel, [BatchSimulationModel, CelerySimulationModel])
    simulations = db.session.query(SimulationPoly).filter_by(user_id=user_id).order_by(SimulationModel.id).all()
    return simulations


def fetch_task_by_sim_id_and_task_id(sim_id: int, task_id: int) -> Union[BatchTaskModel, CeleryTaskModel]:
    """Fetches task by simulation id and task id"""
    TaskPoly = with_polymorphic(TaskModel, [BatchTaskModel, CeleryTaskModel])
    task = db.session.query(TaskPoly).filter_by(simulation_id=sim_id, task_id=task_id).first()
    return task


# errors of the database or the connection, not of the data - retrying later can succeed
DATABASE_FAILURES = (OperationalError, InterfaceError, InternalError)


def fetch_task_summary(sim_id: int) -> dict:
    """Number of tasks in each state and the primaries of all tasks of a simulation, counted by the database"""
    return fetch_task_summaries([sim_id])[sim_id]


def fetch_task_summaries(sim_ids: list[int]) -> dict[int, dict]:
    """fetch_task_summary of many simulations in one query"""
    rows = (
        db.session.query(
            TaskModel.simulation_id,
            TaskModel.task_state,
            func.count(TaskModel.id),
            func.sum(TaskModel.requested_primaries),
            func.sum(TaskModel.simulated_primaries),
        )
        .filter(TaskModel.simulation_id.in_(sim_ids))
        .group_by(TaskModel.simulation_id, TaskModel.task_state)
        .all()
    )
    summaries = {
        sim_id: {"ntasks": 0, "task_states": {}, "requested_primaries": 0, "simulated_primaries": 0}
        for sim_id in sim_ids
    }
    for sim_id, state, count, requested, simulated in rows:
        summary = summaries[sim_id]
        summary["ntasks"] += count
        summary["task_states"][state] = count
        summary["requested_primaries"] += int(requested or 0)
        summary["simulated_primaries"] += int(simulated or 0)
    return summaries


def bulk_update_task_states(sim_id: int, task_updates: list[dict]) -> int:
    """Updates many tasks of one simulation in a single query and a single commit.

    `task_updates` is a list of `{"task_id": int, "update_dict": dict}` entries.
    Returns the number of tasks that were found and updated.
    """
    updates_by_task_id = {update["task_id"]: update["update_dict"] for update in task_updates}
    TaskPoly = with_polymorphic(TaskModel, [BatchTaskModel, CeleryTaskModel])
    tasks = (
        db.session.query(TaskPoly)
        .filter(TaskModel.simulation_id == sim_id, TaskModel.task_id.in_(updates_by_task_id.keys()))
        # locked and read again, in one order so two reports do not deadlock: a cancel committed meanwhile is kept
        .order_by(TaskModel.task_id)
        .with_for_update(of=TaskModel.__table__, key_share=True)
        .populate_existing()
        .all()
    )
    found_task_ids = [task.task_id for task in tasks]
    # one malformed update must not fail the whole batch - its sender would send the whole batch again
    for task in tasks:
        _apply_task_update(task, updates_by_task_id[task.task_id], sim_id)
    try:
        db.session.commit()
    except DATABASE_FAILURES:
        # the database itself is failing, not the data - an error makes the sender (the engine) try the batch again
        db.session.rollback()
        raise
    except Exception as e:  # skipcq: PYL-W0703
        # a value the database rejects only shows up here - retry the tasks one by one, so the others still land
        logging.error("Bulk update of simulation %d rejected by the database, retrying task by task: %s", sim_id, e)
        db.session.rollback()
        for task, task_id in zip(tasks, found_task_ids):
            # the rollback released the locks
            db.session.refresh(task, with_for_update={"key_share": True})
            _apply_task_update(task, updates_by_task_id[task_id], sim_id)
            try:
                db.session.commit()
            except DATABASE_FAILURES:
                db.session.rollback()
                raise
            except Exception as task_error:  # skipcq: PYL-W0703
                # rollback first - the failed commit leaves the session unusable, even for reading task attributes
                db.session.rollback()
                logging.error("Skipping invalid update for task %d of simulation %d: %s", task_id, sim_id, task_error)
    if len(tasks) != len(updates_by_task_id):
        missing = set(updates_by_task_id.keys()) - set(found_task_ids)
        logging.warning("Simulation %d has no tasks with ids %s, skipping their updates", sim_id, sorted(missing))
    return len(tasks)


FINAL_TASK_STATES = (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value)
TASK = TaskModel.__table__.c


def _reported_update():
    """TaskModel.update_state as one UPDATE of a task, for update_reported_tasks"""
    # each new_* parameter is a reported field, NULL when the report has no such field
    state, end = bindparam("new_task_state", type_=String), bindparam("new_end_time", type_=DateTime(timezone=True))
    requested = func.coalesce(
        func.nullif(bindparam("new_requested_primaries", type_=Integer), 0), TASK.requested_primaries
    )
    estimated = bindparam("new_estimated_time", type_=Integer)
    return (
        update(TaskModel.__table__)
        .where(
            TASK.simulation_id == bindparam("sim_id"),
            TASK.task_id == bindparam("new_task_id"),
            # a final state is kept, e.g. a cancel committed meanwhile; the row is locked and checked again
            # (no NOT IN: its list is expanded per run, which a statement run for many rows cannot do)
            *(TASK.task_state != final for final in FINAL_TASK_STATES),
        )
        .values(
            requested_primaries=requested,
            simulated_primaries=case(
                (state == EntityState.COMPLETED.value, requested),
                else_=func.coalesce(
                    func.nullif(bindparam("new_simulated_primaries", type_=Integer), 0), TASK.simulated_primaries
                ),
            ),
            task_state=func.coalesce(state, TASK.task_state),
            estimated_time=case(
                (and_(TASK.end_time.is_(None), end.isnot(None)), None),
                (and_(TASK.end_time.is_(None), estimated.isnot(None)), estimated),
                else_=TASK.estimated_time,
            ),
            start_time=func.coalesce(TASK.start_time, bindparam("new_start_time", type_=DateTime(timezone=True))),
            end_time=func.coalesce(TASK.end_time, end),
            last_update_time=func.now(),
        )
    )


REPORTED_FIELDS = (
    "task_state",
    "requested_primaries",
    "simulated_primaries",
    "estimated_time",
    "start_time",
    "end_time",
)


def update_reported_tasks(sim_id: int, task_updates: list[dict]) -> None:
    """bulk_update_task_states for updates already checked (yaptide/engine/engine.py clean_report), without the ORM:
    one statement run for all tasks at once (20k tasks in 0.6 s instead of 4.2 s, M4 and Postgres), in the order of
    their ids like the other locking updates; no commit

    Changes a task as TaskModel.update_state does; times come as its strings.
    """
    rows = []
    for task_update in sorted(task_updates, key=lambda item: item["task_id"]):
        row = {"sim_id": sim_id, "new_task_id": task_update["task_id"]}
        for name in REPORTED_FIELDS:
            value = task_update["update_dict"].get(name)
            if name in ("start_time", "end_time") and value is not None:
                value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
            row[f"new_{name}"] = value
        rows.append(row)
    if rows:
        db.session.execute(_reported_update(), rows)


def _apply_task_update(task: Union[BatchTaskModel, CeleryTaskModel], update_dict: dict, sim_id: int) -> None:
    """Applies a single task update, a malformed one leaves the task untouched"""
    task_id = task.task_id
    try:
        task.update_state(update_dict)
    except Exception as e:  # skipcq: PYL-W0703
        # update_state may have set some fields before it failed - expiring drops them, the update is skipped whole
        db.session.expire(task)
        logging.error("Skipping invalid update for task %d of simulation %d: %s", task_id, sim_id, e)


def fetch_tasks_by_sim_id(sim_id: int) -> Union[list[BatchTaskModel], list[CeleryTaskModel]]:
    """Fetches tasks by simulation id, sorted by task_id"""
    TaskPoly = with_polymorphic(TaskModel, [BatchTaskModel, CeleryTaskModel])
    tasks = db.session.query(TaskPoly).filter_by(simulation_id=sim_id).order_by(TaskModel.task_id).all()
    return tasks


def fetch_celery_tasks_by_sim_id(sim_id: int) -> list[CeleryTaskModel]:
    """Fetches celery tasks by simulation"""
    tasks = db.session.query(CeleryTaskModel).filter_by(simulation_id=sim_id).all()
    return tasks


def fetch_batch_tasks_by_sim_id(sim_id: int) -> list[BatchTaskModel]:
    """Fetches batch tasks by simulation"""
    tasks = db.session.query(BatchTaskModel).filter_by(simulation_id=sim_id).all()
    return tasks


def fetch_estimators_by_sim_id(sim_id: int) -> list[EstimatorModel]:
    """Fetches estimators by simulation id, sorted by id"""
    estimators = db.session.query(EstimatorModel).filter_by(simulation_id=sim_id).order_by(EstimatorModel.id).all()
    return estimators


def fetch_estimator_names_by_job_id(job_id: int) -> Optional[list[str]]:
    """Fetches estimators names by job id
    Returns a list of estimator names if the simulation exists,
    or None if no simulation is found for the provided job ID.
    """
    simulation_id = fetch_simulation_id_by_job_id(job_id=job_id)
    if not simulation_id:
        return None
    estimator_names_tuples = (
        db.session.query(EstimatorModel.name).filter_by(simulation_id=simulation_id).order_by(EstimatorModel.id).all()
    )
    estimator_names = [name for (name,) in estimator_names_tuples]
    return estimator_names


def fetch_estimator_by_sim_id_and_est_name(sim_id: int, est_name: str) -> EstimatorModel:
    """Fetches estimator by simulation id and estimator name"""
    estimator = db.session.query(EstimatorModel).filter_by(simulation_id=sim_id, name=est_name).first()
    return estimator


def fetch_estimator_id_by_sim_id_and_est_name(sim_id: int, est_name: str) -> Optional[int]:
    """Fetches estimator_id by simulation id and estimator name"""
    estimator_id = db.session.query(EstimatorModel.id).filter_by(simulation_id=sim_id, name=est_name).first()
    return estimator_id[0] if estimator_id else None


def fetch_pages_by_estimator_id(est_id: int) -> list[PageModel]:
    """Fetches pages by estimator id, sorted by page number"""
    pages = db.session.query(PageModel).filter_by(estimator_id=est_id).order_by(PageModel.page_number).all()
    return pages


def fetch_page_by_est_id_and_page_number(est_id: int, page_number: int) -> PageModel:
    """Fetches page by estimator id and page number"""
    page = db.session.query(PageModel).filter_by(estimator_id=est_id, page_number=page_number).first()
    return page


def fetch_pages_by_est_id_and_page_numbers(est_id: int, page_numbers: list) -> PageModel:
    """Fetches page by estimator id and page number"""
    pages = (
        db.session.query(PageModel)
        .filter(and_(PageModel.estimator_id == est_id, PageModel.page_number.in_(page_numbers)))
        .order_by(PageModel.page_number)
        .all()
    )
    return pages


def fetch_pages_metadata_by_est_id(est_id: str) -> EstimatorModel:
    """Fetches estimator by simulation id and estimator name, sorted by page number"""
    pages_metadata = (
        db.session.query(PageModel.page_number, PageModel.page_name, PageModel.page_dimension)
        .filter_by(estimator_id=est_id)
        .order_by(PageModel.page_number)
        .all()
    )
    return pages_metadata


def fetch_all_clusters() -> list[ClusterModel]:
    """Fetches all clusters"""
    clusters = db.session.query(ClusterModel).all()
    return clusters


def fetch_cluster_by_id(cluster_id: int) -> ClusterModel:
    """Fetches cluster by id"""
    cluster = db.session.query(ClusterModel).filter_by(id=cluster_id).first()
    return cluster


def fetch_input_by_sim_id(sim_id: int) -> InputModel:
    """Fetches input by simulation id"""
    input_model = db.session.query(InputModel).filter_by(simulation_id=sim_id).first()
    return input_model


def fetch_logfiles_by_sim_id(sim_id: int) -> LogfilesModel:
    """Fetches logfiles by simulation id"""
    logfiles = db.session.query(LogfilesModel).filter_by(simulation_id=sim_id).first()
    return logfiles


def update_task_state(task: Union[BatchTaskModel, CeleryTaskModel], update_dict: dict) -> None:
    """Updates task state and makes commit"""
    # locked and read again: a cancel committed by another request after this one read the task is kept;
    # key_share (FOR NO KEY UPDATE) does not wait for requests only adding rows that point to this one
    db.session.refresh(task, with_for_update={"key_share": True})
    task.update_state(update_dict)
    db.session.commit()


def update_simulation_state(simulation: Union[BatchSimulationModel, CelerySimulationModel], update_dict: dict) -> None:
    """Updates simulation state and makes commit"""
    # locked and read again: a final state committed by another request after this one read the row is kept;
    # key_share (FOR NO KEY UPDATE) does not wait for a results upload adding estimators of this simulation
    db.session.refresh(simulation, with_for_update={"key_share": True})
    if not simulation.update_state(update_dict):
        logging.warning("Simulation state not updated")
    db.session.commit()


# a user following their simulations is written down at most this often by each process
WATCHING_WRITE_SECONDS = 30
# when this process last wrote each user down (time.monotonic)
_watching_written: dict[int, float] = {}


def note_watching(user_id: int) -> None:
    """Writes down that the user follows the status of their simulations now (UserActivityModel), at most every
    WATCHING_WRITE_SECONDS in this process; commits. A failed write is only logged: the status is still answered.
    """
    if time.monotonic() - _watching_written.get(user_id, float("-inf")) < WATCHING_WRITE_SECONDS:
        return
    _watching_written[user_id] = time.monotonic()
    insert = postgresql.insert if db.engine.dialect.name == "postgresql" else sqlite.insert
    seen = {"user_id": user_id, "seen_at": datetime.now(timezone.utc)}
    try:
        db.session.execute(
            insert(UserActivityModel).values(seen).on_conflict_do_update(index_elements=["user_id"], set_=seen)
        )
        db.session.commit()
    except Exception:  # skipcq: PYL-W0703
        db.session.rollback()
        logging.exception("Writing down that user %d follows their simulations failed", user_id)
