import pytest

from sqlalchemy.orm.scoping import scoped_session

from yaptide.application import create_app

from yaptide.persistence.database import db
from yaptide.persistence.models import UserModel, SimulationModel, TaskModel, ResultModel, create_models


@pytest.fixture()
def db_session():
    _app = create_app()
    with _app.app_context():
        db.create_all()
        yield db.session
        db.drop_all()


def test_create_user(db_session: scoped_session):
    user = UserModel(username="test_user")
    user.set_password("password")
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
