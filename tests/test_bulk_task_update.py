import json
import threading
import time
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
import zmq
from sqlalchemy.exc import OperationalError
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
            "update_key": "key",
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


def test_aggregator_drops_messages_with_wrong_update_key(tmp_path):
    """A message that does not carry the update key of the simulation never reaches the backend"""
    aggregator = TaskUpdateAggregator(
        sim_id=1, update_key="key", backend_url="http://localhost:5000", root_dir=tmp_path, ntasks=1
    )

    aggregator.handle_message({"update_key": "wrong", "task_id": 1, "update_dict": {"simulated_primaries": 10}})
    assert aggregator._pending == {}

    aggregator.handle_message({"update_key": "key", "task_id": 1, "update_dict": {"simulated_primaries": 10}})
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
        """Backend answering 400"""
        raise HTTPError("http://localhost:5000/tasks/bulk", 400, "Bad Request", {}, BytesIO(b"Invalid update key"))

    monkeypatch.setattr(aggregator_module.request, "urlopen", reject)
    aggregator.flush()
    assert aggregator._pending == {}


def test_aggregator_keeps_batch_when_backend_unreachable(tmp_path, monkeypatch):
    """Connection problems are transient, the updates wait for the next flush"""
    aggregator = make_aggregator(tmp_path)

    def unreachable(*args, **kwargs):
        """Backend that cannot be reached"""
        raise URLError("connection refused")

    monkeypatch.setattr(aggregator_module.request, "urlopen", unreachable)
    aggregator.flush()
    assert aggregator._pending == {1: {"simulated_primaries": 10}}


def test_bulk_update_keeps_other_tasks_when_the_database_rejects_a_value(
    app, simulation_with_tasks: CelerySimulationModel
):
    """A value only the database refuses fails the commit - the other tasks still land and the request succeeds"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [
            {"task_id": 1, "update_dict": {"requested_primaries": 2**70}},
            {"task_id": 2, "update_dict": {"simulated_primaries": 600}},
        ],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    tasks = {task.task_id: task for task in CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id)}
    assert tasks[1].requested_primaries == 1000
    assert tasks[2].simulated_primaries == 600


def test_bulk_update_skips_a_malformed_update_as_a_whole(app, simulation_with_tasks: CelerySimulationModel):
    """Fields set before the malformed one must not be saved - the task would end COMPLETED without end_time"""
    client = app.test_client()

    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [{"task_id": 1, "update_dict": {"task_state": EntityState.COMPLETED.value, "end_time": "not a date"}}],
    }
    resp = client.post("/tasks/bulk", json=payload)

    assert resp.status_code == 202
    task = CeleryTaskModel.query.filter_by(simulation_id=simulation_with_tasks.id, task_id=1).first()
    assert task.task_state == EntityState.PENDING.value
    assert task.end_time is None


def test_bulk_update_rejects_payload_that_is_not_an_object(app):
    """A JSON list is not a bulk update"""
    resp = app.test_client().post("/tasks/bulk", json=[1, 2])
    assert resp.status_code == 400


def test_aggregator_keeps_batch_when_bulk_endpoint_is_missing(tmp_path, monkeypatch):
    """A 404 means a backend without /tasks/bulk, e.g. during a deploy - the updates wait for the next flush"""
    aggregator = make_aggregator(tmp_path)

    def not_found(*args, **kwargs):
        """Backend without the bulk endpoint"""
        raise HTTPError("http://localhost:5000/tasks/bulk", 404, "Not Found", {}, BytesIO(b""))

    monkeypatch.setattr(aggregator_module.request, "urlopen", not_found)
    aggregator.flush()
    assert aggregator._pending == {1: {"simulated_primaries": 10}}


def test_aggregator_delivers_messages_still_queued_when_it_stops(tmp_path, monkeypatch):
    """Whatever the socket accepted before a SIGTERM ends up in the final flush, even if the loop never read it"""

    class IdlePoller:
        """Poller that never reports incoming messages, so they stay queued until shutdown"""

        def register(self, *args):
            """Ignores the socket"""

        @staticmethod
        def poll(timeout: int) -> list:
            """Nothing ready"""
            time.sleep(timeout / 1000)
            return []

    monkeypatch.setattr(aggregator_module.zmq, "Poller", IdlePoller)
    monkeypatch.setattr(aggregator_module, "advertised_ip", lambda interface: "127.0.0.1")
    aggregator = TaskUpdateAggregator(
        sim_id=1,
        update_key="key",
        backend_url="http://localhost:5000",
        root_dir=tmp_path,
        ntasks=100,
        flush_interval_seconds=3600,
        idle_timeout_seconds=30,
    )
    sent_payloads = []
    monkeypatch.setattr(aggregator, "send_bulk_update", lambda payload: sent_payloads.append(payload) or True)
    # daemon and a short idle timeout - a failing test must not keep pytest waiting for the aggregator
    thread = threading.Thread(target=aggregator.run, daemon=True)
    thread.start()

    context = zmq.Context()
    push_socket = context.socket(zmq.PUSH)
    try:
        auth_path = tmp_path / ".zmq_auth"
        for _ in range(50):
            if auth_path.exists():
                break
            time.sleep(0.1)
        auth = json.loads(auth_path.read_text())
        push_socket.connect(f"tcp://{auth['host']}:{auth['port']}")
        for task_id in range(1, 21):
            message = {"update_key": "key", "task_id": task_id, "update_dict": {"simulated_primaries": task_id}}
            push_socket.send(json.dumps(message).encode())
        time.sleep(0.5)
    finally:
        aggregator.stop_event.set()
        thread.join(timeout=10)
        push_socket.close(linger=0)
        context.term()

    assert not thread.is_alive()
    delivered = sorted(task["task_id"] for payload in sent_payloads for task in payload["tasks"])
    assert delivered == list(range(1, 21))


def test_aggregator_reads_at_most_the_given_number_of_messages_per_wakeup(tmp_path):
    """A flood of messages must not keep the loop from flushing and from noticing a stop signal"""
    aggregator = make_aggregator(tmp_path)
    context = zmq.Context()
    pull_socket = context.socket(zmq.PULL)
    push_socket = context.socket(zmq.PUSH)
    try:
        port = pull_socket.bind_to_random_port("tcp://127.0.0.1")
        push_socket.connect(f"tcp://127.0.0.1:{port}")
        for task_id in range(1, 16):
            push_socket.send(json.dumps({"update_key": "key", "task_id": task_id, "update_dict": {}}).encode())
        assert pull_socket.poll(2000)
        time.sleep(0.2)
        assert aggregator.receive_pending(pull_socket, max_messages=10) == 10
        assert aggregator.receive_pending(pull_socket, max_messages=10) == 5
    finally:
        push_socket.close(linger=0)
        pull_socket.close(linger=0)
        context.term()


@pytest.mark.parametrize(
    "code, dropped", [(500, False), (503, False), (429, False), (404, False), (422, True), (401, True), (403, True)]
)
def test_aggregator_retries_transient_errors_and_drops_invalid_batches(tmp_path, monkeypatch, code, dropped):
    """Only answers saying the batch itself is wrong drop it, everything else waits for the next flush"""
    aggregator = make_aggregator(tmp_path)

    def answer(*args, **kwargs):
        """Backend answering with the given code"""
        raise HTTPError("http://localhost:5000/tasks/bulk", code, "", {}, BytesIO(b""))

    monkeypatch.setattr(aggregator_module.request, "urlopen", answer)
    aggregator.flush()
    assert (aggregator._pending == {}) is dropped


@pytest.mark.parametrize("task_ids", [(1,), (1, 2)])
def test_bulk_update_fails_when_the_database_itself_fails(app, simulation_with_tasks, monkeypatch, task_ids):
    """An unavailable database is not bad data - the request fails, so the aggregator retries the batch"""

    def failing_commit():
        """Database refusing every write"""
        raise OperationalError("COMMIT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(db.session, "commit", failing_commit)
    payload = {
        "simulation_id": simulation_with_tasks.id,
        "update_key": encode_simulation_auth_token(simulation_id=simulation_with_tasks.id),
        "tasks": [{"task_id": task_id, "update_dict": {"simulated_primaries": 500}} for task_id in task_ids],
    }
    # the test app propagates the exception, a deployed flask answers it with 500
    with pytest.raises(OperationalError):
        app.test_client().post("/tasks/bulk", json=payload)


def test_bulk_update_rejects_a_user_token_as_update_key(app, simulation_with_tasks):
    """A token without simulation_id is an invalid update key, not a server error"""
    from yaptide.routes.utils.tokens import encode_auth_token  # skipcq: PYL-C0415

    token, _ = encode_auth_token(user_id=1)
    payload = {"simulation_id": simulation_with_tasks.id, "update_key": token, "tasks": []}
    assert app.test_client().post("/tasks/bulk", json=payload).status_code == 400
