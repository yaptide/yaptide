"""The trigger telling the engine about direct simulations, on Postgres (set TEST_DATABASE_URI, SQLite has none)"""

import json
import os

import psycopg
import pytest
from sqlalchemy import make_url, text

from yaptide.application import create_app
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    ENGINE_CHANNEL,
    BatchSimulationModel,
    CelerySimulationModel,
    ClusterModel,
    SimulationModel,
    YaptideUserModel,
    prepare_database,
)
from yaptide.utils.enums import EntityState, InputType, SimulationType

URI = os.environ.get("TEST_DATABASE_URI", "")
pytestmark = pytest.mark.skipif(not URI.startswith("postgresql"), reason="notifications need Postgres")


@pytest.fixture
def listener(monkeypatch):
    """Empty Postgres with the models' tables and a connection listening for the engine's events"""
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", URI)
    app = create_app()
    with app.app_context():
        # the tables are dropped at the end, so only an empty database will do
        assert not db.inspect(db.engine).get_table_names(), f"{URI} is not empty"
        db.create_all()
        conninfo = make_url(URI).set(drivername="postgresql").render_as_string(hide_password=False)
        with psycopg.connect(conninfo, autocommit=True) as connection:
            connection.execute(f"LISTEN {ENGINE_CHANNEL}")
            yield connection
        db.session.remove()
        db.drop_all()


def events(connection) -> list[tuple[str, int]]:
    """Events delivered so far"""
    return [
        (payload["event"], payload["simulation"])
        for payload in (json.loads(notify.payload) for notify in connection.notifies(timeout=0.5))
    ]


def direct_simulation(job_state: str = EntityState.PENDING.value) -> CelerySimulationModel:
    """Direct simulation stored as Flask stores it"""
    user = YaptideUserModel(username=f"user{job_state}")
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    simulation = CelerySimulationModel(
        job_id=f"job{job_state}",
        title="events",
        user_id=user.id,
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        job_state=job_state,
    )
    db.session.add(simulation)
    db.session.commit()
    return simulation


def test_stored_cancelled_and_deleted_simulations_send_events(listener):
    """The engine hears what it has to start or stop, after the transaction commits"""
    simulation = direct_simulation()
    simulation_id = simulation.id
    assert events(listener) == [(EntityState.PENDING.value, simulation_id)]

    db.session.query(SimulationModel).filter_by(id=simulation_id).update({"job_state": EntityState.CANCELED.value})
    assert events(listener) == []  # not committed yet
    db.session.commit()
    assert events(listener) == [(EntityState.CANCELED.value, simulation_id)]

    db.session.delete(db.session.get(SimulationModel, simulation_id))
    db.session.commit()
    assert events(listener) == [("DELETED", simulation_id)]


def test_states_the_engine_writes_itself_send_nothing(listener):
    """Running, merging and finished are the engine's own doing"""
    simulation = direct_simulation()
    events(listener)
    for job_state in (EntityState.RUNNING, EntityState.MERGING_QUEUED, EntityState.COMPLETED):
        db.session.query(SimulationModel).filter_by(id=simulation.id).update({"job_state": job_state.value})
        db.session.commit()

    assert events(listener) == []


def test_batch_simulations_send_nothing(listener):
    """HPC simulations are not the engine's"""
    user = YaptideUserModel(username="batch")
    user.set_password("x")
    cluster = ClusterModel(cluster_name="ares")
    db.session.add_all([user, cluster])
    db.session.commit()
    db.session.add(
        BatchSimulationModel(
            job_id="batchjob",
            title="batch",
            user_id=user.id,
            cluster_id=cluster.id,
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            job_state=EntityState.PENDING.value,
        )
    )
    db.session.commit()

    assert events(listener) == []


def test_database_with_tables_from_the_models_only_gets_the_trigger(listener):
    """Deployments where the tables were only ever created from the models get the trigger on start, too"""
    db.session.execute(text('DROP TRIGGER simulation_engine_events ON "Simulation"'))
    db.session.execute(text("DROP FUNCTION notify_engine()"))
    db.session.commit()

    prepare_database()

    triggers = db.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars().all()
    db.session.execute(text("DROP TABLE alembic_version"))
    db.session.commit()
    assert triggers == ["simulation_engine_events"]
