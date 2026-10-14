"""A final state stored by another request (a cancel, a result) is never overwritten by a request that read before it"""

import os

import pytest
from sqlalchemy import text

from yaptide.application import create_app
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import bulk_update_task_states, update_simulation_state, update_task_state
from yaptide.persistence.models import (
    CelerySimulationModel,
    CeleryTaskModel,
    SimulationModel,
    TaskModel,
    YaptideUserModel,
)
from yaptide.utils.enums import EntityState, InputType, SimulationType

END_TIME = "2026-10-14 20:00:00.000000"


@pytest.fixture
def simulation(tmp_path, monkeypatch) -> CelerySimulationModel:
    """Running simulation with one running task, in a database file other connections can write to meanwhile"""
    # TEST_DATABASE_URI runs these on Postgres, where the row locks are real
    uri = os.environ.get("TEST_DATABASE_URI", f"sqlite:///{tmp_path / 'yaptide.db'}")
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", uri)
    app = create_app()
    with app.app_context():
        # the tables are dropped at the end, so only an empty database will do
        assert not db.inspect(db.engine).get_table_names(), f"{uri} is not empty"
        db.create_all()
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
        simulation = CelerySimulationModel(
            job_id="finaljob",
            user_id=user.id,
            input_type=InputType.EDITOR.value,
            sim_type=SimulationType.SHIELDHIT.value,
            title="final",
            job_state=EntityState.RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        db.session.add(
            CeleryTaskModel(
                simulation_id=simulation.id, task_id=1, requested_primaries=1000, task_state=EntityState.RUNNING.value
            )
        )
        db.session.commit()
        yield simulation
        db.session.remove()
        db.drop_all()


def cancel_from_another_request(table: str, column: str) -> None:
    """The user's cancel, committed by another connection after this request has read the row"""
    with db.engine.connect() as other:
        other.execute(text(f'UPDATE "{table}" SET {column} = :state'), {"state": EntityState.CANCELED.value})
        other.commit()


def stored(model, column):
    """Value as stored, read in a fresh session"""
    db.session.remove()
    return db.session.query(column).select_from(model).scalar()


def test_simulation_result_does_not_overwrite_a_cancel(simulation):
    """Results stored after a cancel leave the simulation canceled"""
    assert simulation.job_state == EntityState.RUNNING.value  # read before the cancel
    cancel_from_another_request("Simulation", "job_state")

    update_simulation_state(simulation, {"job_state": EntityState.COMPLETED.value, "end_time": END_TIME})

    assert stored(SimulationModel, SimulationModel.job_state) == EntityState.CANCELED.value


def test_task_report_does_not_overwrite_a_cancel(simulation):
    """A late report of a task does not bring it back from canceled"""
    task = db.session.query(CeleryTaskModel).one()
    assert task.task_state == EntityState.RUNNING.value
    cancel_from_another_request("Task", "task_state")

    update_task_state(task, {"task_state": EntityState.COMPLETED.value})

    assert stored(TaskModel, TaskModel.task_state) == EntityState.CANCELED.value


def test_bulk_task_report_does_not_overwrite_a_cancel(simulation):
    """The same for reports sent in bulk"""
    task = db.session.query(CeleryTaskModel).one()
    assert task.task_state == EntityState.RUNNING.value
    cancel_from_another_request("Task", "task_state")

    bulk_update_task_states(simulation.id, [{"task_id": 1, "update_dict": {"task_state": EntityState.COMPLETED.value}}])

    assert stored(TaskModel, TaskModel.task_state) == EntityState.CANCELED.value
