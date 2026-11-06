"""Finishing tasks early: the request, its way to the tasks (storage for HPC, the engine for direct simulations), and
the direct task stopping at its last whole save"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from yaptide.application import create_app
from yaptide.engine import simulation as engine_simulation
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    BatchTaskModel,
    ClusterModel,
    KeycloakUserModel,
    SimulationModel,
    TaskModel,
)
from yaptide.routes.common_sim_routes import finish_requested_numbers
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

BDO = (Path(__file__).resolve().parent / "res" / "bdo" / "task_1" / "z_profile_0001.bdo").read_bytes()


@pytest.fixture
def client(monkeypatch):
    """Signed in as the owner of a running HPC simulation of 3 tasks (one ended); the finish objects kept in a dict"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    objects = {}
    monkeypatch.setattr(result_storage, "put_finish", lambda sim_id, numbers: objects.__setitem__(sim_id, numbers))
    app = create_app()
    with app.app_context():
        db.create_all()
        user = KeycloakUserModel(username="plgtest")
        other = KeycloakUserModel(username="plgother")
        cluster = ClusterModel(cluster_name="ares")
        db.session.add_all([user, other, cluster])
        db.session.commit()
        simulation = BatchSimulationModel(
            job_id="hpcjob",
            user_id=user.id,
            cluster_id=cluster.id,
            title="hpc",
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            job_state=EntityState.RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        states = {1: EntityState.COMPLETED.value, 2: EntityState.RUNNING.value, 3: EntityState.PENDING.value}
        db.session.add_all(
            BatchTaskModel(simulation_id=simulation.id, task_id=number, task_state=state)
            for number, state in states.items()
        )
        db.session.commit()
        test_client = app.test_client()
        test_client.set_cookie("access_token", encode_auth_token(user.id, is_keycloak=True)[0], domain="127.0.0.1")
        test_client.objects = objects
        test_client.simulation_id = simulation.id
        test_client.other_token = encode_auth_token(other.id, is_keycloak=True)[0]
        yield test_client
        db.session.remove()
        db.drop_all()


def finish(client, **body):
    """A request to finish tasks of the simulation early"""
    return client.post("/tasks/finish", json={"job_id": "hpcjob", **body})


def test_tasks_asked_to_finish_are_noted_and_their_watchers_told(client):
    """Only tasks not ended yet; the finish object names all asked for so far"""
    response = finish(client, task_numbers=[1, 2])
    assert response.status_code == 202 and response.get_json()["task_numbers"] == [2]
    assert client.objects == {client.simulation_id: [2]}

    assert finish(client, all=True).get_json()["task_numbers"] == [2, 3]
    assert client.objects == {client.simulation_id: [2, 3]}
    assert finish_requested_numbers(client.simulation_id) == [2, 3]

    status = client.get("/jobs", query_string={"job_id": "hpcjob", "tasks": "true"}).get_json()
    tasks = {task["task_number"]: task for task in status["job_tasks_status"]}
    assert tasks[2].get("finish_requested") and not tasks[1].get("finish_requested")


@pytest.mark.parametrize("body", [{}, {"task_numbers": []}, {"task_numbers": [0]}, {"task_numbers": "2"}])
def test_a_request_without_tasks_is_refused(client, body):
    assert finish(client, **body).status_code == 400


def test_only_the_owner_of_a_running_simulation_finishes_its_tasks(client):
    client.set_cookie("access_token", client.other_token, domain="127.0.0.1")
    assert finish(client, all=True).status_code in (403, 404)
    assert finish_requested_numbers(client.simulation_id) == []


def test_an_ended_simulation_has_no_tasks_to_finish(client):
    db.session.query(SimulationModel).update({"job_state": EntityState.MERGING_QUEUED.value})
    db.session.commit()
    assert finish(client, all=True).status_code == 409
    assert db.session.query(TaskModel).filter_by(finish_requested=True).count() == 0


SAVING = """
import pathlib, sys, time
work, data = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]).read_bytes()
log = work / "shieldhit_0001.log"
log.write_text("start\\n")
while True:
    with open(work / "dose.bdo", "wb") as out:
        out.write(data[: len(data) // 2]); out.flush(); time.sleep(0.3); out.write(data[len(data) // 2 :])
    with open(log, "a") as out:
        out.write("  Saved all 1 estimator(s)\\n")
    time.sleep(0.2)
"""


def test_a_direct_task_finishes_at_a_whole_save(tmp_path, monkeypatch):
    """Asked to finish, the direct task's simulator stops between saves: its files stay whole, for the merge"""
    monkeypatch.setattr(engine_simulation, "FINISH_CHECK_SECONDS", 0)
    (tmp_path / "data.bin").write_bytes(BDO)
    asked = threading.Event()
    finisher = engine_simulation.Finisher("shieldhit", tmp_path, tmp_path / "shieldhit_0001.log", asked.is_set)
    process = subprocess.Popen(
        [sys.executable, "-c", SAVING, str(tmp_path), str(tmp_path / "data.bin")], cwd=tmp_path, start_new_session=True
    )
    try:
        time.sleep(1)
        finisher(process)
        assert finisher.finished is None and process.poll() is None
        asked.set()
        finisher(process)
        assert finisher.finished is True
        process.wait(timeout=10)
        assert (tmp_path / "dose.bdo").read_bytes() == BDO
    finally:
        if process.poll() is None:
            process.kill()


def test_a_running_simulation_shows_the_progress_of_each_task(client):
    """Per task by number, for a progress bar of many segments: permille of its primaries and its state's letter"""
    db.session.query(TaskModel).filter_by(task_id=2).update({"requested_primaries": 200, "simulated_primaries": 50})
    db.session.commit()
    status = client.get("/jobs", query_string={"job_id": "hpcjob"}).get_json()
    assert status["task_progress"] == {"permille": [0, 250, 0], "states": "CRP"}

    db.session.query(SimulationModel).update({"job_state": EntityState.COMPLETED.value})
    db.session.commit()
    assert "task_progress" not in client.get("/jobs", query_string={"job_id": "hpcjob"}).get_json()
