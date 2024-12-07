from datetime import datetime
import time

from sqlalchemy.orm.scoping import scoped_session
from sqlalchemy.orm import with_polymorphic

from yaptide.utils.enums import PlatformType, EntityState, InputType, SimulationType
from yaptide.persistence.models import (UserModel, YaptideUserModel, KeycloakUserModel, CelerySimulationModel,
                                        BatchSimulationModel, CeleryTaskModel, BatchTaskModel, ClusterModel, InputModel,
                                        EstimatorModel, PageModel)


def test_create_yaptide_user(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test user model creation"""
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.username == db_good_username
    assert user.check_password(db_good_password)


def test_create_keycloak_user(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test keycloak user model creation"""
    user = KeycloakUserModel(username=db_good_username, cert=db_good_password, private_key=db_good_password)
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.username == db_good_username
    assert user.cert == db_good_password


def test_polymorphic_user_fetch(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test polymorphic user fetch"""
    yaptide_user = YaptideUserModel(username=db_good_username)
    yaptide_user.set_password(db_good_password)
    db_session.add(yaptide_user)
    db_session.commit()

    assert yaptide_user.id is not None

    yaptide_user_id = yaptide_user.id

    keycloak_user = KeycloakUserModel(username=db_good_username, cert=db_good_password, private_key=db_good_password)
    db_session.add(keycloak_user)
    db_session.commit()

    assert keycloak_user.id is not None

    keycloak_user_id = keycloak_user.id
    UserPoly = with_polymorphic(UserModel, [YaptideUserModel, KeycloakUserModel])

    fetched_user = db_session.query(UserPoly).filter_by(id=yaptide_user_id).first()
    assert fetched_user is not None
    assert isinstance(fetched_user, YaptideUserModel)
    assert fetched_user.username == db_good_username
    assert fetched_user.check_password(db_good_password)

    fetched_user = db_session.query(UserPoly).filter_by(id=keycloak_user_id).first()
    assert fetched_user is not None
    assert isinstance(fetched_user, KeycloakUserModel)
    assert fetched_user.username == db_good_username
    assert fetched_user.cert == db_good_password


def test_cluster_model_creation(db_session: scoped_session):
    """Test cluster model creation"""
    # create a new cluster
    cluster = ClusterModel(cluster_name='testcluster')
    db_session.add(cluster)
    db_session.commit()

    # retrieve the cluster from the database and check its fields
    assert cluster.id is not None
    assert cluster.cluster_name == 'testcluster'


def test_create_celery_simulation(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test celery simulation creation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    simulation = CelerySimulationModel(job_id='testjob',
                                       user_id=user.id,
                                       input_type=InputType.EDITOR.value,
                                       sim_type=SimulationType.SHIELDHIT.value,
                                       title='testtitle')
    db_session.add(simulation)
    db_session.commit()
    assert simulation.id is not None
    assert simulation.user_id == user.id
    assert simulation.job_id == 'testjob'
    assert simulation.platform == PlatformType.DIRECT.value
    assert simulation.input_type == InputType.EDITOR.value
    assert simulation.sim_type == SimulationType.SHIELDHIT.value
    assert simulation.job_state == EntityState.UNKNOWN.value


def test_create_batch_simulation(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test batch simulation creation"""
    # create a new user
    user = KeycloakUserModel(username=db_good_username, cert=db_good_password, private_key=db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new cluster
    cluster = ClusterModel(cluster_name='testcluster')
    db_session.add(cluster)
    db_session.commit()

    simulation = BatchSimulationModel(job_id='testjob',
                                      user_id=user.id,
                                      cluster_id=cluster.id,
                                      input_type=InputType.EDITOR.value,
                                      sim_type=SimulationType.SHIELDHIT.value,
                                      title='testtitle',
                                      job_dir='testfolder',
                                      array_id=2137,
                                      collect_id=2138)
    db_session.add(simulation)
    db_session.commit()
    assert simulation.id is not None
    assert simulation.array_id is not None
    assert simulation.collect_id is not None
    assert simulation.job_dir is not None
    assert simulation.user_id == user.id
    assert simulation.cluster_id == cluster.id
    assert simulation.job_id == 'testjob'
    assert simulation.platform == PlatformType.BATCH.value
    assert simulation.input_type == InputType.EDITOR.value
    assert simulation.sim_type == SimulationType.SHIELDHIT.value
    assert simulation.job_state == EntityState.UNKNOWN.value


def test_celery_task_model_creation_and_update(db_session: scoped_session, db_good_username: str,
                                               db_good_password: str):
    """Test celery task model creation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    simulation = CelerySimulationModel(job_id='testjob',
                                       user_id=user.id,
                                       input_type=InputType.EDITOR.value,
                                       sim_type=SimulationType.SHIELDHIT.value,
                                       title='testtitle')
    db_session.add(simulation)
    db_session.commit()

    task = CeleryTaskModel(simulation_id=simulation.id,
                           task_id='testtask',
                           requested_primaries=1000,
                           simulated_primaries=0)
    db_session.add(task)
    db_session.commit()

    # retrieve the task from the database and check its fields
    task: CeleryTaskModel = CeleryTaskModel.query.filter_by(simulation_id=simulation.id).first()
    assert task.id is not None
    assert task.task_state == EntityState.PENDING.value

    start_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {
        'celery_id': 'testceleryid',
        'task_state': EntityState.RUNNING.value,
        'simulated_primaries': 500,
        'start_time': start_time
    }
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 500
    assert task.task_state == EntityState.RUNNING.value
    assert task.end_time is None
    assert task.celery_id == 'testceleryid'

    time.sleep(1)

    end_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {'task_state': EntityState.COMPLETED.value, 'end_time': end_time, 'simulated_primaries': 1000}
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 1000
    assert task.task_state == EntityState.COMPLETED.value
    assert task.end_time is not None
    assert task.end_time > task.start_time


def test_batch_task_model_creation_and_update(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test batch task model creation"""
    # create a new user
    user = KeycloakUserModel(username=db_good_username, cert=db_good_password, private_key=db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new cluster
    cluster = ClusterModel(cluster_name='testcluster')
    db_session.add(cluster)
    db_session.commit()

    simulation = BatchSimulationModel(job_id='testjob',
                                      user_id=user.id,
                                      cluster_id=cluster.id,
                                      input_type=InputType.EDITOR.value,
                                      sim_type=SimulationType.SHIELDHIT.value,
                                      title='testtitle',
                                      job_dir='testfolder',
                                      array_id=2137,
                                      collect_id=2138)
    db_session.add(simulation)
    db_session.commit()

    task = BatchTaskModel(simulation_id=simulation.id,
                          task_id='testtask',
                          requested_primaries=1000,
                          simulated_primaries=0)
    db_session.add(task)
    db_session.commit()

    # retrieve the task from the database and check its fields
    task: BatchTaskModel = BatchTaskModel.query.filter_by(simulation_id=simulation.id).first()
    assert task.id is not None
    assert task.task_state == EntityState.PENDING.value

    start_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {'task_state': EntityState.RUNNING.value, 'simulated_primaries': 500, 'start_time': start_time}
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 500
    assert task.task_state == EntityState.RUNNING.value
    assert task.end_time is None

    time.sleep(1)

    end_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {'task_state': EntityState.COMPLETED.value, 'end_time': end_time, 'simulated_primaries': 1000}
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 1000
    assert task.task_state == EntityState.COMPLETED.value
    assert task.end_time is not None
    assert task.end_time > task.start_time


def test_celery_simulation_with_multiple_tasks(db_session: scoped_session, db_good_username: str,
                                               db_good_password: str):
    """Test simulation with multiple tasks"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    simulation = CelerySimulationModel(job_id='testjob',
                                       user_id=user.id,
                                       input_type=InputType.EDITOR.value,
                                       sim_type=SimulationType.SHIELDHIT.value,
                                       title='testtitle')
    db_session.add(simulation)
    db_session.commit()

    task_ids = [str(i) for i in range(100)]
    for task_id in task_ids:
        task = CeleryTaskModel(simulation_id=simulation.id,
                               task_id=task_id,
                               requested_primaries=1000,
                               simulated_primaries=0)
        db_session.add(task)
    db_session.commit()

    tasks: list[CeleryTaskModel] = CeleryTaskModel.query.filter_by(simulation_id=simulation.id).all()
    assert len(tasks) == 100

    start_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {'task_state': EntityState.RUNNING.value, 'simulated_primaries': 1, 'start_time': start_time}
    for task in tasks:
        task.update_state(update_dict=update_dict)
    db_session.commit()

    time.sleep(1)

    update_dict = {'task_state': EntityState.RUNNING.value, 'simulated_primaries': 500}

    for idx, task in enumerate(tasks):
        if idx == 50:
            end_time = datetime.utcnow().isoformat(sep=" ")
            update_dict = {'task_state': EntityState.COMPLETED.value, 'end_time': end_time, 'simulated_primaries': 1000}
        task.update_state(update_dict=update_dict)
    db_session.commit()

    tasks_running: list[CeleryTaskModel] = CeleryTaskModel.query.filter_by(simulation_id=simulation.id,
                                                                           task_state=EntityState.RUNNING.value).all()
    assert len(tasks_running) == 50

    for task in tasks_running:
        assert task.simulated_primaries == 500
        assert task.task_state == EntityState.RUNNING.value
        assert task.end_time is None

    tasks_completed: list[CeleryTaskModel] = CeleryTaskModel.query.filter_by(
        simulation_id=simulation.id, task_state=EntityState.COMPLETED.value).all()

    assert len(tasks_completed) == 50

    for task in tasks_completed:
        assert task.simulated_primaries == 1000
        assert task.task_state == EntityState.COMPLETED.value
        assert task.end_time is not None
        assert task.end_time > task.start_time


def test_create_input(db_session: scoped_session, db_good_username: str, db_good_password: str,
                      payload_editor_dict_data: dict):
    """Test creation of input_model in db for simulation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    simulation = CelerySimulationModel(job_id='testjob',
                                       user_id=user.id,
                                       input_type=InputType.EDITOR.value,
                                       sim_type=SimulationType.SHIELDHIT.value,
                                       title='testtitle')
    db_session.add(simulation)
    db_session.commit()

    # create a new input_model
    input_model = InputModel(simulation_id=simulation.id)
    input_model.data = payload_editor_dict_data
    db_session.add(input_model)
    db_session.commit()

    assert input_model.id is not None
    assert input_model.simulation_id == simulation.id
    assert input_model.data == payload_editor_dict_data


def test_create_result_estimators_and_pages(db_session: scoped_session, db_good_username: str, db_good_password: str,
                                            result_dict_data: dict):
    """Test creation of estimators and pages in db for a result"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    simulation = CelerySimulationModel(job_id='testjob',
                                       user_id=user.id,
                                       input_type=InputType.EDITOR.value,
                                       sim_type=SimulationType.SHIELDHIT.value,
                                       title='testtitle')
    db_session.add(simulation)
    db_session.commit()

    for estimator_dict in result_dict_data["estimators"]:
        file_name = estimator_dict["name"]
        estimator_name = file_name[:-1] if file_name[-1] == "_" else file_name
        estimator = EstimatorModel(name=estimator_name, file_name=file_name, simulation_id=simulation.id)
        estimator.data = estimator_dict["metadata"]
        db_session.add(estimator)
        db_session.commit()

        assert estimator.id is not None
        assert estimator.file_name == file_name
        assert estimator.name == estimator_name
        assert estimator.simulation_id == simulation.id

        for page_dict in estimator_dict["pages"]:
            page = PageModel(page_number=int(page_dict["metadata"]["page_number"]), estimator_id=estimator.id)
            page.data = page_dict
            db_session.add(page)
            db_session.commit()

            assert page.id is not None

    estimators: list[EstimatorModel] = EstimatorModel.query.filter_by(simulation_id=simulation.id).all()
    assert len(estimators) == len(result_dict_data["estimators"])

    for estimator_dict in result_dict_data["estimators"]:
        estimator: EstimatorModel = EstimatorModel.query.filter_by(simulation_id=simulation.id,
                                                                   file_name=estimator_dict["name"]).first()
        assert estimator is not None
        assert estimator.data == estimator_dict["metadata"]

        pages: list[PageModel] = PageModel.query.filter_by(estimator_id=estimator.id).all()
        assert len(pages) == len(estimator_dict["pages"])

        for page_dict in estimator_dict["pages"]:
            page: PageModel = PageModel.query.filter_by(estimator_id=estimator.id,
                                                        page_number=int(page_dict["metadata"]["page_number"])).first()
            assert page is not None
            assert page.data == page_dict
