import pytest

from sqlalchemy.orm.scoping import scoped_session

from yaptide.application import create_app

from yaptide.persistence.database import db
from yaptide.persistence.models import (
    UserModel,
    SimulationModel,
    TaskModel,
    ClusterModel,
    ResultModel
)


@pytest.fixture()
def db_session():
    _app = create_app()
    with _app.app_context():
        db.create_all()
        yield db.session
        db.drop_all()


def test_create_user(db_session: scoped_session):
    user = UserModel(username="testuser")
    user.set_password("testpassword")
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.username == 'testuser'
    assert user.check_password('testpassword')


def test_cluster_model_creation(db_session: scoped_session):
    """Test cluster model creation"""
    # create a new user
    user = UserModel(username='testuser')
    user.set_password("testpassword")
    db_session.add(user)
    db_session.commit()

    # create a new cluster for the user
    cluster = ClusterModel(
        user_id=user.id,
        cluster_name='testcluster',
        cluster_username='testuser',
        cluster_ssh_key='ssh_key'
    )
    db_session.add(cluster)
    db_session.commit()

    # retrieve the cluster from the database and check its fields
    cluster = ClusterModel.query.filter_by(user_id=user.id).first()
    assert cluster is not None
    assert cluster.cluster_name == 'testcluster'
    assert cluster.cluster_username == 'testuser'
    assert cluster.cluster_ssh_key == 'ssh_key'


def test_simulation_model_creation(db_session: scoped_session):
    """Test simulation model creation"""
    # create a new user
    user = UserModel(username='testuser')
    user.set_password("testpassword")
    db_session.add(user)
    db_session.commit()

    # create a new simulation for the user
    simulation = SimulationModel(
        job_id='testjob',
        user_id=user.id,
        platform=SimulationModel.Platform.DIRECT.value,
        input_type=SimulationModel.InputType.YAPTIDE_PROJECT.value,
        sim_type=SimulationModel.SimType.SHIELDHIT.value
    )
    db_session.add(simulation)
    db_session.commit()

    # retrieve the simulation from the database and check its fields
    simulation = SimulationModel.query.filter_by(user_id=user.id).first()
    assert simulation.id is not None
    assert simulation.job_id == 'testjob'
    assert simulation.platform == SimulationModel.Platform.DIRECT.value
    assert simulation.input_type == SimulationModel.InputType.YAPTIDE_PROJECT.value
    assert simulation.sim_type == SimulationModel.SimType.SHIELDHIT.value


# def test_task_model_creation(db_session: scoped_session):
#     """Test task model creation"""
#     # create a new user
#     user = UserModel(username='testuser')
#     user.set_password("testpassword")
#     db_session.add(user)
#     db_session.commit()

#     # create a new simulation for the user
#     simulation = SimulationModel(
#         job_id='testjob',
#         user_id=user.id,
#         platform=SimulationModel.Platform.DIRECT.value,
#         input_type=SimulationModel.InputType.YAPTIDE_PROJECT.value,
#         sim_type=SimulationModel.SimType.SHIELDHIT.value
#     )
#     db_session.add(simulation)
#     db_session.commit()

#     # create a new task for the simulation
#     task = TaskModel(
#         simulation_id=simulation.id,
#         requested_primaries=1000,
#         simulated_primaries=500,
#         status=SimulationModel.JobStatus.PENDING.value,
#         time_hours=1,
#         time_minutes=30,
#         time_seconds=0
#     )
#     db_session.add(task)
#     db_session.commit()

#     # retrieve the task from the database and check its fields
#     task = TaskModel.query.filter_by(simulation_id=simulation.id).first()
#     assert task.id is not None
