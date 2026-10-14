"""The engine on a local Ray cluster: simulations stored by Flask run, report, merge, fail, cancel and recover"""

import os
import platform
import queue
import time
from pathlib import Path
from unittest import mock

import pytest
import ray
from sqlalchemy.exc import OperationalError

from yaptide.engine import engine as engine_module
from yaptide.engine.engine import Engine
from yaptide.engine.simulation import WORK_DIR_PREFIX, backend_app
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    BatchTaskModel,
    ClusterModel,
    CelerySimulationModel,
    CeleryTaskModel,
    LogfilesModel,
    PageModel,
    SimulationModel,
    TaskModel,
    YaptideUserModel,
)
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

pytestmark = pytest.mark.skipif(platform.system() == "Windows", reason="the fake simulator is a POSIX script")

REPO_DIR = Path(__file__).resolve().parent.parent
FAKE_SIMULATOR_DIR = REPO_DIR / "tests" / "res" / "fake_shieldhit"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """Local Ray cluster and database file shared by the engine here and the merges in the Ray workers"""
    root = tmp_path_factory.mktemp("engine")
    work_root = root / "work"
    work_root.mkdir()
    env_vars = {
        "FLASK_SQLALCHEMY_DATABASE_URI": f"sqlite:///{root / 'yaptide.db'}",
        "PATH": os.pathsep.join([str(FAKE_SIMULATOR_DIR), os.environ["PATH"]]),
        "TMPDIR": str(work_root),
        "PYTHONPATH": str(REPO_DIR),
    }
    saved = {key: os.environ.get(key) for key in env_vars}
    os.environ.update(env_vars)
    backend_app.cache_clear()
    ray.init(num_cpus=2, runtime_env={"env_vars": env_vars}, include_dashboard=False)
    yield work_root
    ray.shutdown()
    backend_app.cache_clear()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def client(cluster):
    """Flask test client of a logged in user, with an empty database"""
    app = backend_app()
    with app.app_context():
        db.create_all()
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
        yield client
        db.session.remove()
        db.drop_all()


@pytest.fixture
def engine(client):
    """Engine of the test, its leftovers stopped afterwards"""
    engine = Engine()
    yield engine
    for simulation_id in list(engine.running):
        engine.stop(simulation_id)


def submit(client, beam: str, ntasks: int = 2) -> int:
    """Stores a simulation through the API, as the UI does; the beam marker chooses what the fake simulator does"""
    payload = {
        "input_type": "files",
        "sim_type": "shieldhit",
        "ntasks": ntasks,
        "input_files": {"beam.dat": f"NSTAT 100 0\n{beam}\n", "geo.dat": "", "mat.dat": "", "detect.dat": ""},
    }
    response = client.post("/jobs/direct", json=payload)
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    return db.session.query(SimulationModel.id).filter_by(job_id=job_id).scalar()


def run_until(engine: Engine, condition, timeout: float = 60) -> None:
    """Sweeps until the condition holds, as the engine does when it cannot listen"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        engine.sweep()
        engine.save_progress()
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError("condition not reached")


def state(simulation_id: int) -> str:
    """Simulation state as stored"""
    db.session.remove()
    return db.session.get(SimulationModel, simulation_id).job_state


def task_states(simulation_id: int) -> list[str]:
    """Task states as stored, by task id"""
    db.session.remove()
    tasks = db.session.query(TaskModel).filter_by(simulation_id=simulation_id).order_by(TaskModel.task_id)
    return [task.task_state for task in tasks]


def work_dirs(work_root: Path) -> list[Path]:
    """Task directories left on disk"""
    return list(work_root.glob(f"{WORK_DIR_PREFIX}*"))


def test_simulation_runs_and_its_results_are_stored(client, engine, cluster):
    """Tasks run, report and complete; the merge stores the results and removes the task directories"""
    simulation_id = submit(client, "regular run")
    assert state(simulation_id) == EntityState.PENDING.value

    run_until(engine, lambda: state(simulation_id) == EntityState.COMPLETED.value)

    assert task_states(simulation_id) == [EntityState.COMPLETED.value] * 2
    assert db.session.query(PageModel).count() > 0
    assert not engine.running
    assert not work_dirs(cluster)


def test_failing_tasks_fail_the_simulation_with_their_logs(client, engine):
    """No results to merge: the simulation fails and the logs of its tasks are kept"""
    simulation_id = submit(client, "FAKE_FAIL")

    run_until(engine, lambda: state(simulation_id) == EntityState.FAILED.value and not engine.running)

    assert task_states(simulation_id) == [EntityState.FAILED.value] * 2
    assert db.session.query(LogfilesModel).filter_by(simulation_id=simulation_id).count() == 1
    assert not engine.running


def test_cancel_kills_the_simulator_and_cleans_up(client, engine, cluster):
    """A cancel stored by Flask stops the running simulator processes and removes their directories"""
    simulation_id = submit(client, "FAKE_SLEEP")
    run_until(engine, lambda: len(list(cluster.glob(f"{WORK_DIR_PREFIX}{simulation_id}_*/fake.pid"))) == 2)
    pids = [int(path.read_text()) for path in cluster.glob(f"{WORK_DIR_PREFIX}{simulation_id}_*/fake.pid")]
    job_id = db.session.get(SimulationModel, simulation_id).job_id

    assert client.delete("/jobs/direct", query_string={"job_id": job_id}).status_code == 200
    run_until(engine, lambda: not engine.running)

    assert state(simulation_id) == EntityState.CANCELED.value
    assert task_states(simulation_id) == [EntityState.CANCELED.value] * 2
    run_until(engine, lambda: not any(_alive(pid) for pid in pids), timeout=20)
    assert not work_dirs(cluster)


def _alive(pid: int) -> bool:
    """Whether a process still runs"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_overdue_task_is_stopped_and_fails(client, engine, monkeypatch):
    """A task running longer than allowed is killed and counts as failed"""
    simulation_id = submit(client, "FAKE_SLEEP", ntasks=1)
    run_until(engine, lambda: task_states(simulation_id) == [EntityState.RUNNING.value])
    monkeypatch.setattr(engine_module, "TASK_SECONDS_LIMIT", 0)
    engine.stop_overdue()

    run_until(engine, lambda: state(simulation_id) == EntityState.FAILED.value and not engine.running)

    assert task_states(simulation_id) == [EntityState.FAILED.value]


def test_recovery_fails_lost_simulations_and_starts_pending_ones(client, engine):
    """After a restart, what was running is lost and marked failed; what was waiting runs"""
    lost = submit(client, "regular run")
    db.session.query(SimulationModel).filter_by(id=lost).update({"job_state": EntityState.RUNNING.value})
    db.session.query(TaskModel).filter_by(simulation_id=lost).update({"task_state": EntityState.RUNNING.value})
    db.session.commit()
    waiting = submit(client, "regular run")

    engine.recover()
    assert state(lost) == EntityState.FAILED.value
    assert task_states(lost) == [EntityState.FAILED.value] * 2

    run_until(engine, lambda: state(waiting) == EntityState.COMPLETED.value)
    assert lost not in engine.running


def test_submit_stores_everything_the_engine_needs_in_one_go(client):
    """The engine may pick the simulation up right after the commit: state, tasks and input are all there"""
    simulation_id = submit(client, "regular run", ntasks=3)

    simulation = db.session.get(CelerySimulationModel, simulation_id)
    assert simulation.job_state == EntityState.PENDING.value
    assert simulation.input_type == InputType.FILES.value
    assert simulation.sim_type == SimulationType.SHIELDHIT.value
    assert "beam.dat" in simulation.inputs[0].data["input_files"]
    assert [task.task_id for task in db.session.query(CeleryTaskModel).filter_by(simulation_id=simulation_id)] == [
        0,
        1,
        2,
    ]


def test_cancel_leaves_other_simulations_alone(client, engine):
    """Stopping one simulation must not kill the tasks of another waiting for the same cores"""
    cancelled = submit(client, "FAKE_SLEEP")  # both cores
    run_until(engine, lambda: task_states(cancelled) == [EntityState.RUNNING.value] * 2)
    waiting = submit(client, "regular run")
    run_until(engine, lambda: waiting in engine.running)

    job_id = db.session.get(SimulationModel, cancelled).job_id
    assert client.delete("/jobs/direct", query_string={"job_id": job_id}).status_code == 200
    run_until(engine, lambda: state(waiting) == EntityState.COMPLETED.value and not engine.running)

    assert task_states(waiting) == [EntityState.COMPLETED.value] * 2


def test_merge_does_not_wait_for_a_free_core(client, engine):
    """A finished simulation is merged while other simulations keep every core busy"""
    finished = submit(client, "regular run", ntasks=1)
    busy = submit(client, "FAKE_SLEEP")
    run_until(engine, lambda: state(finished) == EntityState.COMPLETED.value)

    assert state(busy) == EntityState.RUNNING.value


def test_simulation_deleted_after_its_tasks_does_not_break_the_engine(client, engine):
    """A simulation gone before its merge starts is dropped, the others keep running"""
    deleted = submit(client, "regular run", ntasks=1)
    other = submit(client, "FAKE_SLEEP", ntasks=1)
    engine.sweep()
    ray.wait(list(engine.running[deleted].tasks), timeout=60)
    db.session.delete(db.session.get(SimulationModel, deleted))
    db.session.commit()

    engine.sweep()

    assert deleted not in engine.running
    assert other in engine.running


def run_events_until(engine: Engine, condition, timeout: float = 60) -> None:
    """Handles only the events in the queue, as the engine does while listening, until the condition holds"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            engine.handle(*engine.events.get(timeout=0.2))
        except queue.Empty:
            pass
        engine.save_progress()
        if condition():
            return
    raise AssertionError("condition not reached")


def test_events_alone_run_a_simulation(client, engine):
    """The event Postgres sends on submit starts it, Ray's events of finished tasks and merge complete it"""
    simulation_id = submit(client, "regular run")
    engine.handle(EntityState.PENDING.value, simulation_id)

    run_events_until(engine, lambda: state(simulation_id) == EntityState.COMPLETED.value and not engine.running)

    assert task_states(simulation_id) == [EntityState.COMPLETED.value] * 2


def test_cancel_event_stops_the_simulation(client, engine, cluster):
    """The event Postgres sends on cancel stops the tasks at once"""
    simulation_id = submit(client, "FAKE_SLEEP")
    engine.handle(EntityState.PENDING.value, simulation_id)
    run_events_until(engine, lambda: task_states(simulation_id) == [EntityState.RUNNING.value] * 2)

    engine.handle(EntityState.CANCELED.value, simulation_id)

    assert not engine.running
    assert not work_dirs(cluster)


def test_database_failure_while_collecting_is_retried(client, engine, monkeypatch):
    """A task finishing while the database is down is taken again by the sweep, not failed and forgotten"""
    original = Engine.save_task_updates
    failures = []

    def database_down_once(simulation_id: int, updates: list[dict]) -> None:
        """The first save of finished tasks meets a database that is restarting"""
        if not failures and any("end_time" in update["update_dict"] for update in updates):
            failures.append(simulation_id)
            raise OperationalError("UPDATE", {}, Exception("the database system is shutting down"))
        original(simulation_id, updates)

    monkeypatch.setattr(Engine, "save_task_updates", staticmethod(database_down_once))
    simulation_id = submit(client, "regular run")
    engine.handle(EntityState.PENDING.value, simulation_id)
    deadline = time.time() + 60
    while not failures and time.time() < deadline:
        try:
            engine.handle(*engine.events.get(timeout=0.2))
        except OperationalError:
            db.session.rollback()
        except queue.Empty:
            pass
    assert failures, "the failure was not reached"
    assert simulation_id in engine.running

    run_until(engine, lambda: state(simulation_id) == EntityState.COMPLETED.value and not engine.running)

    assert task_states(simulation_id) == [EntityState.COMPLETED.value] * 2


@ray.remote
def crashing_submit(simulation_id: int) -> None:
    """A submit whose worker died"""
    raise RuntimeError(f"worker of submit {simulation_id} died")


def test_hpc_events_submit_once_and_a_crashed_submit_fails(client, engine):
    """The engine hands a stored HPC simulation to the cluster gateway once; a crash before the claim is
    repeated, one after it fails the simulation and cancels what reached the cluster
    """
    user = db.session.query(YaptideUserModel).one()
    cluster = ClusterModel(cluster_name="ares")
    db.session.add(cluster)
    db.session.commit()
    simulation = BatchSimulationModel(
        job_id="hpc",
        user_id=user.id,
        cluster_id=cluster.id,
        title="hpc",
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        job_state=EntityState.PENDING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    engine.cluster = mock.Mock()
    submits = []

    def submit_crashing(simulation_id: int):
        """The first submit dies before claiming the job directory, the second right after claiming it"""
        submits.append(simulation_id)
        if len(submits) == 2:
            db.session.execute(
                BatchSimulationModel.__table__.update()
                .where(BatchSimulationModel.__table__.c.id == simulation_id)
                .values(job_dir=f"/scratch/yaptide_runs/{simulation_id}_1")
            )
            db.session.commit()
        return crashing_submit.remote(simulation_id)

    engine.cluster.submit.remote.side_effect = submit_crashing
    engine.cluster.cancel.remote.side_effect = lambda simulation_id: ray.put(None)

    engine.handle(EntityState.PENDING.value, simulation.id, "BATCH")
    engine.handle(EntityState.PENDING.value, simulation.id, "BATCH")
    assert engine.cluster.submit.remote.call_count == 1
    run_events_until(engine, lambda: state(simulation.id) == EntityState.FAILED.value)

    assert engine.cluster.submit.remote.call_count == 2
    assert not engine.submitting
    engine.cluster.cancel.remote.assert_called_once_with(simulation.id)


def hpc_simulation(state: str = EntityState.PENDING.value) -> int:
    """A submitted HPC simulation with two tasks"""
    user = db.session.query(YaptideUserModel).one()
    cluster = ClusterModel(cluster_name="ares")
    db.session.add(cluster)
    db.session.commit()
    simulation = BatchSimulationModel(
        job_id="hpc",
        user_id=user.id,
        cluster_id=cluster.id,
        title="hpc",
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        job_state=state,
        array_id=1,
        collect_id=2,
    )
    simulation.tasks = [BatchTaskModel(task_id=task_id, requested_primaries=1000) for task_id in (1, 2)]
    db.session.add_all([simulation, *simulation.tasks])
    db.session.commit()
    return simulation.id


def test_hpc_progress_is_read_from_storage(client, engine, monkeypatch):
    """The tasks' reports in storage move their tasks and the simulation; an unchanged report is not read again"""
    simulation_id = hpc_simulation()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    prefix = f"simulations/{simulation_id}/progress/"
    reports = {
        prefix + "task_0001.json": ("e1", {"task_state": "RUNNING", "simulated_primaries": 300, "job_dir": "x"}),
        prefix + "task_0002.json": ("e2", {"task_state": "RUNNING"}),
    }
    reads = []
    monkeypatch.setattr(
        engine_module.result_storage, "progress_reports", lambda sim_id: {k: v[0] for k, v in reports.items()}
    )
    monkeypatch.setattr(
        engine_module.result_storage,
        "read_report",
        lambda key: reads.append(key) or {"task_id": 99, "update": reports[key][1]},
    )

    engine.read_hpc_progress()
    assert state(simulation_id) == EntityState.RUNNING.value
    db.session.remove()
    first = db.session.query(TaskModel).filter_by(simulation_id=simulation_id, task_id=1).one()
    assert first.simulated_primaries == 300  # the task from the object's name, unknown fields ignored

    reports[prefix + "task_0001.json"] = ("e3", {"task_state": "COMPLETED"})
    reports[prefix + "task_0002.json"] = ("e2", {"task_state": "RUNNING"})
    reads.clear()
    engine.read_hpc_progress()
    assert reads == [prefix + "task_0001.json"]


def test_unreachable_storage_skips_a_round(client, engine, monkeypatch):
    """Progress that cannot be read now is read next time; the engine keeps going"""
    hpc_simulation()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")

    def unreachable(sim_id: int) -> dict:
        """Storage restarting"""
        raise ConnectionError(f"storage unreachable for {sim_id}")

    monkeypatch.setattr(engine_module.result_storage, "progress_reports", unreachable)

    engine.read_hpc_progress()


def test_hpc_cancel_goes_into_storage(client, engine, monkeypatch):
    """The tasks learn about a cancel from storage, also after the user's certificate expired"""
    simulation_id = hpc_simulation(EntityState.CANCELED.value)
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    cancels = []
    monkeypatch.setattr(engine_module.result_storage, "put_cancel", cancels.append)
    engine.cluster = mock.Mock()
    engine.cluster.cancel.remote.side_effect = lambda sim_id: ray.put(None)

    engine.handle(EntityState.CANCELED.value, simulation_id, "BATCH")

    assert cancels == [simulation_id]
    engine.cluster.cancel.remote.assert_called_once_with(simulation_id)
