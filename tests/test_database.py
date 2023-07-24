from datetime import datetime
import time

from sqlalchemy.orm.scoping import scoped_session

from yaptide.persistence.models import (
    YaptideUserModel,
    PlgridUserModel,
    SimulationModel,
    TaskModel,
    ClusterModel,
    InputModel,
    EstimatorModel,
    PageModel
)


def test_create_yaptide_user(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test user model creation"""
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.username == db_good_username
    assert user.check_password(db_good_password)


def test_create_plgrid_user(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test plgrid user model creation"""
    user = PlgridUserModel(username=db_good_username, certificate=db_good_password, auth_provider="PLGRID")
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.username == db_good_username
    assert user.certificate == db_good_password


def test_cluster_model_creation(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test cluster model creation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new cluster for the user
    cluster = ClusterModel(user_id=user.id,
                           cluster_name='testcluster',
                           cluster_username='testuser',
                           cluster_ssh_key='ssh_key')
    db_session.add(cluster)
    db_session.commit()

    # retrieve the cluster from the database and check its fields
    cluster = ClusterModel.query.filter_by(user_id=user.id).first()
    assert cluster is not None
    assert cluster.cluster_name == 'testcluster'
    assert cluster.cluster_username == 'testuser'
    assert cluster.cluster_ssh_key == 'ssh_key'


def test_simulation_model_creation(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test simulation model creation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(job_id='testjob',
                                 user_id=user.id,
                                 platform=SimulationModel.Platform.DIRECT.value,
                                 input_type=SimulationModel.InputType.EDITOR.value,
                                 sim_type=SimulationModel.SimType.SHIELDHIT.value,
                                 title='testtitle',
                                 update_key_hash='testkey')
    db_session.add(simulation)
    db_session.commit()

    # retrieve the simulation from the database and check its fields
    simulation: SimulationModel = SimulationModel.query.filter_by(user_id=user.id).first()
    assert simulation.id is not None
    assert simulation.job_id == 'testjob'
    assert simulation.platform == SimulationModel.Platform.DIRECT.value
    assert simulation.input_type == SimulationModel.InputType.EDITOR.value
    assert simulation.sim_type == SimulationModel.SimType.SHIELDHIT.value
    assert simulation.job_state == SimulationModel.JobState.PENDING.value


def test_task_model_creation_and_update(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test task model creation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(job_id='testjob',
                                 user_id=user.id,
                                 platform=SimulationModel.Platform.DIRECT.value,
                                 input_type=SimulationModel.InputType.EDITOR.value,
                                 sim_type=SimulationModel.SimType.SHIELDHIT.value,
                                 title='testtitle',
                                 update_key_hash='testkey')
    db_session.add(simulation)
    db_session.commit()

    # create a new task for the simulation
    task = TaskModel(simulation_id=simulation.id, task_id='testtask', requested_primaries=1000, simulated_primaries=0)
    db_session.add(task)
    db_session.commit()

    # retrieve the task from the database and check its fields
    task: TaskModel = TaskModel.query.filter_by(simulation_id=simulation.id).first()
    assert task.id is not None
    assert task.task_state == SimulationModel.JobState.PENDING.value

    start_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {
        'task_state': SimulationModel.JobState.RUNNING.value,
        'simulated_primaries': 500,
        'start_time': start_time
    }
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 500
    assert task.task_state == SimulationModel.JobState.RUNNING.value
    assert task.end_time is None

    time.sleep(1)

    end_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {
        'task_state': SimulationModel.JobState.COMPLETED.value,
        'end_time': end_time,
        'simulated_primaries': 1000
    }
    task.update_state(update_dict=update_dict)
    assert task.simulated_primaries == 1000
    assert task.task_state == SimulationModel.JobState.COMPLETED.value
    assert task.end_time is not None
    assert task.end_time > task.start_time


def test_simulation_with_multiple_tasks(db_session: scoped_session, db_good_username: str, db_good_password: str):
    """Test simulation with multiple tasks"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(job_id='testjob',
                                 user_id=user.id,
                                 platform=SimulationModel.Platform.DIRECT.value,
                                 input_type=SimulationModel.InputType.EDITOR.value,
                                 sim_type=SimulationModel.SimType.SHIELDHIT.value,
                                 title='testtitle',
                                 update_key_hash='testkey')
    db_session.add(simulation)
    db_session.commit()

    task_ids = [f"task_{i}" for i in range(100)]
    for task_id in task_ids:
        task = TaskModel(simulation_id=simulation.id, task_id=task_id, requested_primaries=1000, simulated_primaries=0)
        db_session.add(task)
    db_session.commit()

    tasks: list[TaskModel] = TaskModel.query.filter_by(simulation_id=simulation.id).all()
    assert len(tasks) == 100

    start_time = datetime.utcnow().isoformat(sep=" ")
    update_dict = {
        'task_state': SimulationModel.JobState.RUNNING.value,
        'simulated_primaries': 1,
        'start_time': start_time
    }
    for task in tasks:
        task.update_state(update_dict=update_dict)
    db_session.commit()

    time.sleep(1)

    update_dict = {'task_state': SimulationModel.JobState.RUNNING.value, 'simulated_primaries': 500}

    for idx, task in enumerate(tasks):
        if idx == 50:
            end_time = datetime.utcnow().isoformat(sep=" ")
            update_dict = {
                'task_state': SimulationModel.JobState.COMPLETED.value,
                'end_time': end_time,
                'simulated_primaries': 1000
            }
        task.update_state(update_dict=update_dict)
    db_session.commit()

    tasks_running: list[TaskModel] = TaskModel.query.filter_by(
        simulation_id=simulation.id, task_state=SimulationModel.JobState.RUNNING.value).all()
    assert len(tasks_running) == 50

    for task in tasks_running:
        assert task.simulated_primaries == 500
        assert task.task_state == SimulationModel.JobState.RUNNING.value
        assert task.end_time is None

    tasks_completed: list[TaskModel] = TaskModel.query.filter_by(
        simulation_id=simulation.id, task_state=SimulationModel.JobState.COMPLETED.value).all()

    assert len(tasks_completed) == 50

    for task in tasks_completed:
        assert task.simulated_primaries == 1000
        assert task.task_state == SimulationModel.JobState.COMPLETED.value
        assert task.end_time is not None
        assert task.end_time > task.start_time


def test_create_input(db_session: scoped_session, db_good_username: str, db_good_password: str, payload_editor_dict_data: dict):
    """Test creation of input_model in db for simulation"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(job_id='testjob',
                                 user_id=user.id,
                                 platform=SimulationModel.Platform.DIRECT.value,
                                 input_type=SimulationModel.InputType.EDITOR.value,
                                 sim_type=SimulationModel.SimType.SHIELDHIT.value,
                                 title='testtitle',
                                 update_key_hash='testkey')
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


def test_create_result_estimators_and_pages(db_session: scoped_session, db_good_username: str, db_good_password: str, result_dict_data: dict):
    """Test creation of estimators and pages in db for a result"""
    # create a new user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(job_id='testjob',
                                 user_id=user.id,
                                 platform=SimulationModel.Platform.DIRECT.value,
                                 input_type=SimulationModel.InputType.EDITOR.value,
                                 sim_type=SimulationModel.SimType.SHIELDHIT.value,
                                 title='testtitle',
                                 update_key_hash='testkey')
    db_session.add(simulation)
    db_session.commit()

    for estimator_dict in result_dict_data["estimators"]:
        estimator = EstimatorModel(name=estimator_dict["name"], simulation_id=simulation.id)
        estimator.data = estimator_dict["metadata"]
        db_session.add(estimator)
        db_session.commit()

        assert estimator.id is not None
        assert estimator.name == estimator_dict["name"]
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
        estimator: EstimatorModel = EstimatorModel.query.filter_by(
            simulation_id=simulation.id, name=estimator_dict["name"]).first()
        assert estimator is not None
        assert estimator.data == estimator_dict["metadata"]

        pages: list[PageModel] = PageModel.query.filter_by(estimator_id=estimator.id).all()
        assert len(pages) == len(estimator_dict["pages"])

        for page_dict in estimator_dict["pages"]:
            page: PageModel = PageModel.query.filter_by(
                estimator_id=estimator.id, page_number=int(page_dict["metadata"]["page_number"])).first()
            assert page is not None
            assert page.data == page_dict
