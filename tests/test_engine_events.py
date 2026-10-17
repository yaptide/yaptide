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
    SIMULATION_CHANNEL,
    BatchSimulationModel,
    CelerySimulationModel,
    CeleryTaskModel,
    ClusterModel,
    SimulationModel,
    YaptideUserModel,
    prepare_database,
)
from yaptide.routes import events_routes
from yaptide.routes.utils.utils import update_state_from_tasks
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


def test_batch_simulations_send_events_with_their_platform(listener):
    """The engine submits stored HPC simulations too, so it has to know which ones they are"""
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

    simulation_id = db.session.query(BatchSimulationModel.id).scalar()
    assert [json.loads(notify.payload) for notify in listener.notifies(timeout=0.5)] == [
        {"simulation": simulation_id, "platform": "BATCH", "event": EntityState.PENDING.value}
    ]


def test_database_with_tables_from_the_models_only_gets_the_triggers(listener):
    """Deployments where the tables were only ever created from the models get the triggers on start, too"""
    db.session.execute(text('DROP TRIGGER simulation_engine_events ON "Simulation"'))
    db.session.execute(text("DROP FUNCTION notify_engine()"))
    db.session.execute(text('DROP TRIGGER simulation_stream_events ON "Simulation"'))
    db.session.execute(text("DROP FUNCTION notify_simulation()"))
    db.session.commit()

    prepare_database()

    triggers = db.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars().all()
    db.session.execute(text("DROP TABLE alembic_version"))
    db.session.commit()
    assert sorted(triggers) == ["simulation_engine_events", "simulation_stream_events"]


def stream_events(connection) -> list[dict]:
    """Events for the UI's streams delivered so far"""
    return [
        json.loads(notify.payload)
        for notify in connection.notifies(timeout=0.5)
        if notify.channel == SIMULATION_CHANNEL
    ]


def test_new_simulations_state_partial_results_and_progress_wake_the_streams_of_its_user(listener):
    """The UI's streams follow new simulations, the state, partial results and saves of the tasks' progress, not
    every write to the simulation
    """
    listener.execute(f"LISTEN {SIMULATION_CHANNEL}")
    simulation = direct_simulation(EntityState.RUNNING.value)

    simulation.partial_primaries = 300
    db.session.commit()
    simulation.title = "renamed"
    db.session.commit()
    update_state_from_tasks(simulation, states_changed=False)
    simulation.job_state = EntityState.COMPLETED.value
    db.session.commit()
    update_state_from_tasks(simulation, states_changed=False)

    assert stream_events(listener) == [{"simulation": simulation.id, "user": simulation.user_id}] * 4


def test_a_save_of_progress_moving_the_state_wakes_the_streams_once(listener):
    """The engine saves the tasks of a simulation once per cycle; one event, also when the state moves with it"""
    simulation = direct_simulation(EntityState.PENDING.value)
    db.session.add(CeleryTaskModel(simulation_id=simulation.id, task_id=1, task_state=EntityState.RUNNING.value))
    db.session.commit()
    listener.execute(f"LISTEN {SIMULATION_CHANNEL}")

    update_state_from_tasks(simulation)

    assert db.session.get(SimulationModel, simulation.id).job_state == EntityState.RUNNING.value
    assert stream_events(listener) == [{"simulation": simulation.id, "user": simulation.user_id}]


def test_streams_of_the_user_are_woken_with_the_simulation(listener):
    """The events server's listener hands each stream of the user the simulation that changed"""
    simulation = direct_simulation(EntityState.RUNNING.value)
    subscribers = events_routes.Subscribers()
    wakeup = subscribers.subscribe(simulation.user_id, URI)
    other_user = subscribers.subscribe(simulation.user_id + 1, URI)
    assert wakeup.get(timeout=5) is None  # connected: anything may have changed meanwhile

    simulation.partial_primaries = 300
    db.session.commit()

    assert wakeup.get(timeout=5) == simulation.id
    assert other_user.get(timeout=5) is None and other_user.empty()
