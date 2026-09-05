import json
import threading
import time
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
import zmq
from yaptide.application import create_app
from yaptide.batch import aggregator as aggregator_module
from yaptide.batch.aggregator import TaskUpdateAggregator
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, CeleryTaskModel, YaptideUserModel
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


@pytest.fixture
def app():
    """Flask app with an empty database, recreated for every test"""
    _app = create_app()
    with _app.app_context():
        db.create_all()
        yield _app
        db.drop_all()


@pytest.fixture
def simulation_with_tasks(app) -> CelerySimulationModel:
    """Simulation with two pending tasks, as created right after job submission"""
    user = YaptideUserModel(username="Gandalf")
    user.set_password("Mellon")
    db.session.add(user)
    db.session.commit()

    simulation = CelerySimulationModel(
        job_id="bulkjob",
        user_id=user.id,
        input_type=InputType.EDITOR.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="bulktitle",
    )
    db.session.add(simulation)
    db.session.commit()

    for task_id in (1, 2):
        db.session.add(CeleryTaskModel(simulation_id=simulation.id, task_id=task_id, requested_primaries=1000))
    db.session.commit()
    return simulation


def test_bulk_update_updates_all_tasks(app, simulation_with_tasks: CelerySimulationModel):
    """Single request updates every task listed in the payload"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"task_state": EntityState.RUNNING.value, "simulated_primaries": 500}},
            {"task_id": 2, "update_dict": {"task_state": EntityState.RUNNING.value, "simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    tasks = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id).order_by(CeleryTaskModel.task_id)
    simulated_primaries = [task.simulated_primaries for task in tasks]
    assert simulated_primaries == [500, 600]
    assert all(task.task_state == EntityState.RUNNING.value for task in tasks)


def test_bulk_update_skips_invalid_task_update_and_keeps_the_rest(app, simulation_with_tasks: CelerySimulationModel):
    """One malformed update must not fail the batch, the aggregator would retry the whole batch forever"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"end_time": "not a date"}},
            {"task_id": 2, "update_dict": {"simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=2).first()
    assert task.simulated_primaries == 600


def test_bulk_update_rejects_invalid_update_key(app, simulation_with_tasks: CelerySimulationModel):
    """Updates signed for another simulation are refused"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id + 1),
        "tasks": [{"task_id": 1, "update_dict": {"simulated_primaries": 500}}],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 400
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=1).first()
    assert task.simulated_primaries == 0


def test_aggregator_batches_updates_from_tasks(tmp_path, monkeypatch):
    """Updates pushed by several tasks leave the aggregator as one bulk request"""
    # the aggregator listens on the cluster internal network only, here that has to be the loopback
    monkeypatch.setattr(aggregator_module, "advertised_ip", lambda interface: "127.0.0.1")
    aggregator = TaskUpdateAggregator(
        sim_id=1,
        update_key="key",
        backend_url="http://localhost:5000",
        root_dir=tmp_path,
        ntasks=2,
        flush_interval_seconds=0.2,
        idle_timeout_seconds=5,
    )
    sent_payloads = []
    monkeypatch.setattr(aggregator, "send_bulk_update", lambda payload: sent_payloads.append(payload) or True)

    thread = threading.Thread(target=aggregator.run)
    thread.start()

    auth_path = tmp_path / ".zmq_auth"
    for _ in range(50):
        if auth_path.exists():
            break
        time.sleep(0.1)
    auth = json.loads(auth_path.read_text())

    context = zmq.Context()
    push_socket = context.socket(zmq.PUSH)
    push_socket.setsockopt(zmq.LINGER, 0)
    push_socket.connect(f"tcp://{auth['host']}:{auth['port']}")
    for task_id in (1, 2):
        message = {
            "secret": auth["secret"],
            "task_id": task_id,
            "update_dict": {"task_state": EntityState.COMPLETED.value},
        }
        push_socket.send(json.dumps(message).encode())

    # both tasks reported a terminal state, so the aggregator finishes on its own
    thread.join(timeout=10)
    push_socket.close()
    context.term()

    assert not thread.is_alive()
    assert not auth_path.exists()
    updated_task_ids = sorted(task["task_id"] for payload in sent_payloads for task in payload["tasks"])
    assert updated_task_ids == [1, 2]
    assert all(payload["update_key"] == "key" for payload in sent_payloads)


def test_aggregator_drops_messages_with_wrong_secret(tmp_path):
    """A message that does not carry the ephemeral secret never reaches the backend"""
    aggregator = TaskUpdateAggregator(
        sim_id=1, update_key="key", backend_url="http://localhost:5000", root_dir=tmp_path, ntasks=1
    )

    aggregator.handle_message({"secret": "wrong", "task_id": 1, "update_dict": {"simulated_primaries": 10}})
    assert aggregator._pending == {}

    aggregator.handle_message({"secret": aggregator.secret, "task_id": 1, "update_dict": {"simulated_primaries": 10}})
    assert aggregator._pending == {1: {"simulated_primaries": 10}}


def make_aggregator(tmp_path) -> TaskUpdateAggregator:
    """Aggregator with one pending update, never started"""
    aggregator = TaskUpdateAggregator(
        sim_id=1, update_key="key", backend_url="http://localhost:5000", root_dir=tmp_path, ntasks=1
    )
    aggregator.store_update(1, {"simulated_primaries": 10})
    return aggregator


def test_aggregator_drops_batch_rejected_by_backend(tmp_path, monkeypatch):
    """A 4xx answer means the batch is invalid, retrying it would block every later update"""
    aggregator = make_aggregator(tmp_path)

    def reject(*args, **kwargs):
        raise HTTPError("http://localhost:5000/tasks/bulk", 400, "Bad Request", {}, BytesIO(b"Invalid update key"))

    monkeypatch.setattr(aggregator_module.request, "urlopen", reject)
    aggregator.flush()
    assert aggregator._pending == {}


def test_aggregator_keeps_batch_when_backend_unreachable(tmp_path, monkeypatch):
    """Connection problems are transient, the updates wait for the next flush"""
    aggregator = make_aggregator(tmp_path)

    def unreachable(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(aggregator_module.request, "urlopen", unreachable)
    aggregator.flush()
    assert aggregator._pending == {1: {"simulated_primaries": 10}}
