"""The engine on a local Ray cluster: simulations stored by Flask run, report, merge, fail, cancel and recover"""

import os
import platform
import queue
import time
from pathlib import Path
from unittest import mock

import pytest
import ray
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import OperationalError

from yaptide.engine import engine as engine_module
from yaptide.engine.engine import Engine
from yaptide.engine.simulation import WORK_DIR_PREFIX, backend_app
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    InputModel,
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


def stored_results(work_root: Path) -> list[str]:
    """Result files the tasks left for the merges: in the bucket when one is configured, otherwise in the directory
    standing in for it
    """
    if result_storage.configured():
        client = result_storage._internal()  # skipcq: PYL-W0212
        listing = client.list_objects_v2(Bucket=os.environ["RESULTS_S3_BUCKET"], Prefix=result_storage.WORK_PREFIX)
        return [item["Key"] for item in listing.get("Contents", [])]
    return [str(path) for path in work_root.glob("yaptide_objects/**/*.tar.gz")]


def test_simulation_runs_and_its_results_are_stored(client, engine, cluster):
    """Tasks run, report and complete; the merge stores the results and removes the task directories"""
    simulation_id = submit(client, "regular run")
    assert state(simulation_id) == EntityState.PENDING.value

    run_until(engine, lambda: state(simulation_id) == EntityState.COMPLETED.value)

    assert task_states(simulation_id) == [EntityState.COMPLETED.value] * 2
    assert db.session.query(PageModel).count() > 0
    assert not engine.running
    assert not work_dirs(cluster)
    run_until(engine, lambda: not stored_results(cluster), timeout=20)


def test_saves_of_running_tasks_become_partial_results(client, engine, cluster):
    """A save half way through the tasks goes to storage, is merged and stored while they run; the final results
    replace it
    """
    simulation_id = submit(client, "FAKE_SAVES")

    run_until(engine, lambda: db.session.get(SimulationModel, simulation_id).partial_primaries is not None)

    assert state(simulation_id) == EntityState.RUNNING.value
    assert db.session.get(SimulationModel, simulation_id).partial_primaries == 100
    assert db.session.query(PageModel).count() > 0
    assert len(stored_results(cluster)) == 2
    run_until(engine, lambda: state(simulation_id) == EntityState.COMPLETED.value)
    run_until(engine, lambda: not stored_results(cluster), timeout=20)
    # the step of saving goes to the tasks only, the stored input is as the user sent it
    stored = db.session.query(InputModel).filter_by(simulation_id=simulation_id).one().data
    assert re.search(r"^NSTAT\s+\d+\s+0$", stored["input_files"]["beam.dat"], re.MULTILINE)


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
    run_until(engine, lambda: not stored_results(cluster), timeout=20)


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


def test_recovery_fails_lost_simulations_and_starts_pending_ones(client, engine, cluster):
    """After a restart, what was running is lost and marked failed, with what its tasks stored; what was waiting
    runs
    """
    lost = submit(client, "regular run")
    db.session.query(SimulationModel).filter_by(id=lost).update({"job_state": EntityState.RUNNING.value})
    db.session.query(TaskModel).filter_by(simulation_id=lost).update({"task_state": EntityState.RUNNING.value})
    db.session.commit()
    saved = cluster / "save.tar.gz"
    saved.write_bytes(b"a save of a lost task")
    result_storage.put_file(result_storage.work_key(lost, 0), saved)
    assert stored_results(cluster)
    waiting = submit(client, "regular run")

    engine.recover()
    assert state(lost) == EntityState.FAILED.value
    assert task_states(lost) == [EntityState.FAILED.value] * 2
    assert not stored_results(cluster)

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


def hpc_simulation(state: str = EntityState.PENDING.value, job_id: str = "hpc") -> int:
    """A submitted HPC simulation with two tasks"""
    user = db.session.query(YaptideUserModel).one()
    cluster = ClusterModel(cluster_name="ares")
    db.session.add(cluster)
    db.session.commit()
    simulation = BatchSimulationModel(
        job_id=job_id,
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


def test_last_reports_are_read_after_the_simulation_completed(client, engine, monkeypatch):
    """The collect job may complete a simulation before the engine read its tasks' last reports"""
    simulation_id = hpc_simulation(EntityState.COMPLETED.value)
    db.session.get(BatchSimulationModel, simulation_id).end_time = datetime.now(timezone.utc)
    old_id = hpc_simulation(EntityState.COMPLETED.value, "old")
    db.session.get(BatchSimulationModel, old_id).end_time = datetime.now(timezone.utc) - timedelta(hours=1)
    db.session.commit()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    listed = []
    monkeypatch.setattr(
        engine_module.result_storage,
        "progress_reports",
        lambda sim_id: listed.append(sim_id) or {f"hpc/{sim_id}/progress/task_0001.json": "e1"},
    )
    monkeypatch.setattr(
        engine_module.result_storage, "read_report", lambda key: {"update": {"task_state": "COMPLETED"}}
    )

    engine.read_hpc_progress()

    assert listed == [simulation_id]
    db.session.remove()
    task = db.session.query(TaskModel).filter_by(simulation_id=simulation_id, task_id=1).one()
    assert task.task_state == EntityState.COMPLETED.value


def test_hpc_progress_is_read_from_storage(client, engine, monkeypatch):
    """The tasks' reports in storage move their tasks and the simulation; an unchanged report is not read again"""
    simulation_id = hpc_simulation()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    prefix = f"hpc/{simulation_id}/progress/"
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


def too_deep(key: str) -> dict:
    """A report nested deeper than the JSON parser goes"""
    raise RecursionError(f"maximum recursion depth exceeded reading {key}")


@pytest.mark.parametrize(
    "bad",
    [{"update": []}, {"update": "x"}, [], "x", None, too_deep],
    ids=["update list", "update string", "list", "string", "null", "too deep"],
)
def test_malformed_report_does_not_stop_the_round(client, engine, monkeypatch, bad):
    """A malformed report is left out and not read again; the other reports of the round are still saved"""
    simulation_ids = [hpc_simulation(), hpc_simulation(job_id="other")]
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")

    def listing(sim_id: int) -> dict:
        """Every simulation has one malformed report, one good one and objects that are not its tasks' reports"""
        prefix = f"hpc/{sim_id}/progress/"
        return {
            prefix + "task_0001.json": "bad",
            prefix + "task_0002.json": "good",
            prefix + "nested/task_0001.json": "nested",
            f"hpc/{sim_id + 100}/progress/task_0001.json": "foreign",
        }

    def read(key: str):
        """The good report for task 2, the malformed one otherwise"""
        reads.append(key)
        if key.endswith("task_0002.json"):
            return {"update": {"task_state": "RUNNING", "simulated_primaries": 700}}
        return bad(key) if callable(bad) else bad

    reads = []
    monkeypatch.setattr(engine_module.result_storage, "progress_reports", listing)
    monkeypatch.setattr(engine_module.result_storage, "read_report", read)

    engine.read_hpc_progress()

    assert sorted(reads) == sorted(
        f"hpc/{sim_id}/progress/task_000{task}.json" for sim_id in simulation_ids for task in (1, 2)
    )
    db.session.remove()
    for simulation_id in simulation_ids:
        tasks = {task.task_id: task for task in db.session.query(TaskModel).filter_by(simulation_id=simulation_id)}
        assert tasks[1].task_state == EntityState.PENDING.value
        assert (tasks[2].task_state, tasks[2].simulated_primaries) == (EntityState.RUNNING.value, 700)

    reads.clear()
    engine.read_hpc_progress()
    assert not reads


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


def test_failed_hpc_cancel_is_repeated_every_few_minutes(client, engine, monkeypatch):
    """A cancel that did not reach the cluster is repeated by the engine, not more often than allowed, until the job
    directory is forgotten
    """
    simulation_id = hpc_simulation(EntityState.CANCELED.value)
    db.session.get(BatchSimulationModel, simulation_id).job_dir = f"/scratch/yaptide_runs/{simulation_id}_1"
    db.session.commit()
    engine.cluster = mock.Mock()
    engine.cluster.cancel.remote.side_effect = lambda sim_id: ray.put(None)

    engine.handle(EntityState.CANCELED.value, simulation_id, "BATCH")
    # the cancel failed on the cluster, the job directory stays recorded
    engine.handle("CANCELLED_ON_CLUSTER", simulation_id)
    engine.retry_cancels()
    engine.sweep()
    assert engine.cluster.cancel.remote.call_count == 1  # tried a moment ago

    monkeypatch.setattr(engine_module, "CANCEL_RETRY_SECONDS", 0)
    engine.retry_cancels()
    assert engine.cluster.cancel.remote.call_count == 2
    engine.handle("CANCELLED_ON_CLUSTER", simulation_id)

    db.session.get(BatchSimulationModel, simulation_id).job_dir = None  # done
    db.session.commit()
    engine.retry_cancels()
    assert engine.cluster.cancel.remote.call_count == 2
    assert not engine.cancel_tried


def test_cleanup_of_a_failed_submit_is_repeated_but_not_at_each_restart(client, engine, monkeypatch):
    """A submit that failed after reaching the cluster keeps its directory until the cancel succeeds; a simulation
    that ran and failed keeps it for good. A restarted engine does not log in at once for what it tried before.
    """
    failed_submit = hpc_simulation(EntityState.FAILED.value, job_id="submit")
    ran = hpc_simulation(EntityState.FAILED.value, job_id="ran")
    simulation = db.session.get(BatchSimulationModel, failed_submit)
    simulation.array_id = simulation.collect_id = None
    for simulation_id in (failed_submit, ran):
        db.session.get(BatchSimulationModel, simulation_id).job_dir = f"/scratch/yaptide_runs/{simulation_id}_1"
    db.session.commit()
    engine.cluster = mock.Mock()
    engine.cluster.cancel.remote.side_effect = lambda sim_id: ray.put(None)

    engine.recover()
    engine.retry_cancels()
    assert engine.cluster.cancel.remote.call_count == 0

    monkeypatch.setattr(engine_module, "CANCEL_RETRY_SECONDS", 0)
    engine.retry_cancels()
    engine.cluster.cancel.remote.assert_called_once_with(failed_submit)


def test_bad_reports_are_left_out_and_others_still_saved(client, engine, monkeypatch):
    """A report with a huge task number or nonsense values does not stop the reports of other simulations"""
    simulation_id = hpc_simulation()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    reports = {
        "hpc/1/progress/task_99999999999999999999.json": ("e1", {"task_state": "RUNNING"}),
        "hpc/1/progress/task_0001.json": (
            "e2",
            {"task_state": "HACKED", "simulated_primaries": -5, "requested_primaries": 10**30, "start_time": "x"},
        ),
        "hpc/1/progress/task_0002.json": ("e3", {"task_state": "RUNNING", "simulated_primaries": 700}),
    }
    reads = []
    monkeypatch.setattr(
        engine_module.result_storage, "progress_reports", lambda sim_id: {k: v[0] for k, v in reports.items()}
    )
    monkeypatch.setattr(
        engine_module.result_storage, "read_report", lambda key: reads.append(key) or {"update": reports[key][1]}
    )

    engine.read_hpc_progress()

    assert "hpc/1/progress/task_99999999999999999999.json" not in reads  # left out by its name, never fetched
    db.session.remove()
    tasks = {task.task_id: task for task in db.session.query(TaskModel).filter_by(simulation_id=simulation_id)}
    assert (tasks[1].task_state, tasks[1].simulated_primaries) == (EntityState.PENDING.value, 0)
    assert (tasks[2].task_state, tasks[2].simulated_primaries) == (EntityState.RUNNING.value, 700)

    reads.clear()
    engine.read_hpc_progress()
    assert not reads  # unchanged reports, also the unusable ones, are not read again


def test_partial_merges_are_limited_and_a_failed_one_is_repeated(engine, monkeypatch):
    """Partial merges hold every task's results in memory next to the simulators: a few at once; one that fails
    does not count as stored, so the next round tries again
    """
    started = []
    monkeypatch.setattr(
        engine_module, "partial_merge_task", mock.Mock(remote=lambda *args: started.append(args[0]) or ray.put(False))
    )
    monkeypatch.setattr(engine, "watch", lambda *args: None)
    for simulation_id in (1, 2, 3):
        engine.running[simulation_id] = engine_module.Running(
            tasks={f"ref{simulation_id}": 1}, work_dirs={}, requested_primaries=1000, saves={1: ("key", 100)}
        )
        engine.merge_partial(simulation_id, engine.running[simulation_id])
    assert started == [1, 2]

    # the merge of 1 stored nothing: the slot goes to 3, and 1 is due again from the same primaries
    engine.partial_merged(1, engine.running[1])
    assert engine.running[1].partial is None and engine.running[1].partial_primaries == 0
    engine.merge_partial(3, engine.running[3])
    engine.merge_partial(1, engine.running[1])
    assert started == [1, 2, 3]
    engine.partial_merged(2, engine.running[2])
    engine.merge_partial(1, engine.running[1])
    assert started == [1, 2, 3, 1]
    engine.running.clear()


def test_saves_of_hpc_tasks_become_partial_results_at_most_once_a_minute(client, engine, monkeypatch):
    """The saves HPC tasks put into storage are merged on the server as those of direct tasks: once they cover
    enough new primaries, at most once a minute, only the reported tasks' own objects within the size limit, and
    not once the simulation stopped running, when they are removed
    """
    simulation_id = hpc_simulation(EntityState.RUNNING.value)
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    first, second = (f"hpc/{simulation_id}/progress/task_000{task}.json" for task in (1, 2))
    reports = {first: ("e1", {"task_state": "RUNNING", "saved_primaries": 100}), second: ("e2", {})}
    saves = [result_storage.work_key(simulation_id, task) for task in (1, 2)]
    sizes = {saves[0]: 10, saves[1]: 10, result_storage.work_key(simulation_id, 3): 10}
    monkeypatch.setattr(
        engine_module.result_storage, "progress_reports", lambda sim_id: {k: v[0] for k, v in reports.items()}
    )
    monkeypatch.setattr(engine_module.result_storage, "read_report", lambda key: {"update": reports[key][1]})
    monkeypatch.setattr(engine_module.result_storage, "stored_sizes", lambda prefix: sizes)
    merges, deleted = [], []
    monkeypatch.setattr(
        engine_module, "partial_merge_task", mock.Mock(remote=lambda *args: merges.append(args) or ray.put(True))
    )
    monkeypatch.setattr(engine_module, "delete_task_results", mock.Mock(remote=deleted.append))
    monkeypatch.setattr(engine, "watch", lambda *args: None)

    def report(etag: str, task: str, primaries: int) -> list:
        """A task reports a new save; the merges started so far"""
        reports[task] = (etag, {"saved_primaries": primaries})
        engine.read_hpc_progress()
        return merges

    engine.read_hpc_progress()
    assert merges == [(simulation_id, saves[:1], 100, result_storage.HPC_SAVES_MAX_BYTES)]
    engine.handle("PARTIAL", simulation_id)
    assert engine.hpc_partials[simulation_id].partial_primaries == 100
    db.session.remove()
    assert db.session.query(TaskModel).filter_by(simulation_id=simulation_id, task_id=1).one().simulated_primaries == 0

    assert len(report("e3", second, 200)) == 1  # within the minute
    monkeypatch.setattr(engine_module, "HPC_PARTIAL_SECONDS", 0)
    engine.read_hpc_progress()
    assert merges[-1][1:3] == (saves, 300)
    engine.handle("PARTIAL", simulation_id)
    assert len(report("e4", first, 150)) == 2  # 50 more of 2000 requested is too few
    monkeypatch.setattr(engine_module.result_storage, "HPC_SAVES_MAX_BYTES", 15)
    assert len(report("e5", first, 400)) == 2  # too large to merge here
    monkeypatch.setattr(engine_module.result_storage, "HPC_SAVES_MAX_BYTES", 20)

    db.session.query(SimulationModel).filter_by(id=simulation_id).update({"job_state": "MERGING_QUEUED"})
    db.session.commit()
    assert len(report("e6", first, 900)) == 2
    assert deleted == [simulation_id] and simulation_id not in engine.hpc_partials
