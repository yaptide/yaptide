import logging
from typing import Optional, Union

from sqlalchemy import and_
from sqlalchemy.orm import with_polymorphic

from yaptide.persistence.database import db
from yaptide.persistence.models import (BatchSimulationModel, BatchTaskModel, CelerySimulationModel, CeleryTaskModel,
                                        ClusterModel, EstimatorModel, InputModel, KeycloakUserModel, LogfilesModel,
                                        PageModel, SimulationModel, TaskModel, UserModel, YaptideUserModel)


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
    """Fetches simulations by user id"""
    SimulationPoly = with_polymorphic(SimulationModel, [BatchSimulationModel, CelerySimulationModel])
    simulations = db.session.query(SimulationPoly).filter_by(user_id=user_id).all()
    return simulations


def fetch_task_by_sim_id_and_task_id(sim_id: int, task_id: str) -> Union[BatchTaskModel, CeleryTaskModel]:
    """Fetches task by simulation id and task id"""
    TaskPoly = with_polymorphic(TaskModel, [BatchTaskModel, CeleryTaskModel])
    task = db.session.query(TaskPoly).filter_by(simulation_id=sim_id, task_id=task_id).first()
    return task


def fetch_tasks_by_sim_id(sim_id: int) -> Union[list[BatchTaskModel], list[CeleryTaskModel]]:
    """Fetches tasks by simulation id"""
    TaskPoly = with_polymorphic(TaskModel, [BatchTaskModel, CeleryTaskModel])
    tasks = db.session.query(TaskPoly).filter_by(simulation_id=sim_id).all()
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
    """Fetches estimators by simulation id"""
    estimators = db.session.query(EstimatorModel).filter_by(simulation_id=sim_id).all()
    return estimators


def fetch_estimator_names_by_job_id(job_id: int) -> Optional[list[str]]:
    """Fetches estimators names by job id
    Returns a list of estimator names if the simulation exists,
    or None if no simulation is found for the provided job ID.
    """
    simulation_id = fetch_simulation_id_by_job_id(job_id=job_id)
    if not simulation_id:
        return None
    estimator_names_tuples = db.session.query(EstimatorModel.name).filter_by(simulation_id=simulation_id).all()
    estimator_names = [name for (name, ) in estimator_names_tuples]
    return estimator_names


def fetch_estimator_by_sim_id_and_est_name(sim_id: int, est_name: str) -> EstimatorModel:
    """Fetches estimator by simulation id and estimator name"""
    estimator = db.session.query(EstimatorModel).filter_by(simulation_id=sim_id, name=est_name).first()
    return estimator


def fetch_estimator_by_sim_id_and_file_name(sim_id: int, file_name: str) -> EstimatorModel:
    """Fetches estimator by simulation id and estimator name"""
    estimator = db.session.query(EstimatorModel).filter_by(simulation_id=sim_id, file_name=file_name).first()
    return estimator


def fetch_estimator_id_by_sim_id_and_est_name(sim_id: int, est_name: str) -> Optional[int]:
    """Fetches estimator_id by simulation id and estimator name"""
    estimator = db.session.query(EstimatorModel.id).filter_by(simulation_id=sim_id, name=est_name).first()
    return estimator[0] if estimator else None


def fetch_pages_by_estimator_id(est_id: int) -> list[PageModel]:
    """Fetches pages by estimator id"""
    pages = db.session.query(PageModel).filter_by(estimator_id=est_id).all()
    return pages


def fetch_page_by_est_id_and_page_number(est_id: int, page_number: int) -> PageModel:
    """Fetches page by estimator id and page number"""
    page = db.session.query(PageModel).filter_by(estimator_id=est_id, page_number=page_number).first()
    return page


def fetch_pages_by_est_id_and_page_numbers(est_id: int, page_numbers: list) -> PageModel:
    """Fetches page by estimator id and page number"""
    pages = db.session.query(PageModel).filter(
        and_(PageModel.estimator_id == est_id, PageModel.page_number.in_(page_numbers))).all()
    return pages


def fetch_pages_metadata_by_est_id(est_id: str) -> EstimatorModel:
    """Fetches estimator by simulation id and estimator name"""
    pages_metadata = db.session.query(PageModel.page_number, PageModel.page_name,
                                      PageModel.page_dimension).filter_by(estimator_id=est_id).all()
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
    task.update_state(update_dict)
    db.session.commit()


def update_simulation_state(simulation: Union[BatchSimulationModel, CelerySimulationModel], update_dict: dict) -> None:
    """Updates simulation state and makes commit"""
    if simulation.update_state(update_dict):
        db.session.commit()
    else:
        logging.warning("Simulation state not updated, skipping commit")
