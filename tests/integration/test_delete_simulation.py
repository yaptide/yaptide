import pytest  # skipcq: PY-W2000
from sqlalchemy.orm.scoping import scoped_session
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.persistence.models import (
    YaptideUserModel,
    CelerySimulationModel,
)
import json


@pytest.fixture(scope="function")
def setup_data(db_session: scoped_session, db_good_username: str, db_good_password: str, client):
    # Create user
    user = YaptideUserModel(username=db_good_username)
    user.set_password(db_good_password)
    db_session.add(user)
    db_session.commit()
    assert user.id is not None
    assert user.username == db_good_username
    assert user.check_password(db_good_password)

    # Login user
    resp = client.post("/auth/login",
                       data=json.dumps(dict(username=db_good_username, password=db_good_password)),
                       content_type='application/json')
    data = json.loads(resp.data.decode())
    assert {'refresh_exp', 'access_exp', 'message'} == set(data.keys())
    assert resp.status_code == 202
    assert resp.headers['Set-Cookie']

    # Create simulation
    simulation_completed = CelerySimulationModel(job_id='test_job_completed',
                                                 user_id=user.id,
                                                 input_type=InputType.EDITOR.value,
                                                 sim_type=SimulationType.SHIELDHIT.value,
                                                 title='testtitle',
                                                 update_key_hash='testkey',
                                                 job_state=EntityState.COMPLETED.value)
    simulation_pending = CelerySimulationModel(job_id='test_job_pending',
                                               user_id=user.id,
                                               input_type=InputType.EDITOR.value,
                                               sim_type=SimulationType.SHIELDHIT.value,
                                               title='testtitle',
                                               update_key_hash='testkey',
                                               job_state=EntityState.PENDING.value)
    db_session.add(simulation_completed)
    db_session.add(simulation_pending)
    db_session.commit()

    yield


def test_delete_simulation_successfull(setup_data, db_session: scoped_session, client):
    # Delete simulation
    response = client.delete("/user/simulations", query_string={"job_id": "test_job_completed"})
    assert response.status_code == 200

    # Verify that the simulation is deleted
    resp = client.get("/user/simulations")
    data = json.loads(resp.data.decode())
    assert resp.status_code == 200
    simulation_completed = [sim for sim in data["simulations"] if sim["job_id"] == "test_job_completed"]
    assert len(simulation_completed) == 0


def test_delete_simulation_invalid_job_id(setup_data, client):
    # Delete simulation with an invalid job_id
    response = client.delete("/user/simulations", query_string={"job_id": "invalid_job"})
    assert response.status_code == 404


def test_delete_simulation_invalid_state(setup_data, client):
    # Delete simulation with an invalid state (PENDING)
    response = client.delete("/user/simulations", query_string={"job_id": "test_job_pending"})
    assert response.status_code == 403

    # Verify that the simulation is not deleted
    resp = client.get("/user/simulations")
    data = json.loads(resp.data.decode())
    assert resp.status_code == 200
    simulation_pending = [sim for sim in data["simulations"] if sim["job_id"] == "test_job_pending"]
    assert len(simulation_pending) == 1
