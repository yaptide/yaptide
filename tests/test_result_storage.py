"""Result pages in object storage: written there on upload, read through signed links, removed with the simulation"""

import json
from pathlib import Path
from unittest import mock

import pytest

from yaptide.application import create_app
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, PageModel, SimulationModel, YaptideUserModel
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

RESULTS = json.loads((Path(__file__).parent / "res" / "json_with_results.json").read_text())["estimators"]


@pytest.fixture
def client():
    """Test client with an empty database, recreated for every test"""
    app = create_app()
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def storage(monkeypatch) -> dict:
    """Object storage kept in a dict, as configured on a deployment with a results bucket"""
    objects = {}
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "put_page", lambda key, page: objects.update({key: page}) or 123)
    monkeypatch.setattr(result_storage, "page_url", lambda key: f"https://storage.test/{key}?signature")
    return objects


@pytest.fixture
def sim_id(client) -> int:
    """Running direct simulation of a logged in user, with input given as files"""
    user = YaptideUserModel(username="Gandalf")
    user.set_password("Mellon")
    db.session.add(user)
    db.session.commit()
    simulation = CelerySimulationModel(
        job_id="storagejob",
        user_id=user.id,
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="storage",
        job_state=EntityState.RUNNING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
    return simulation.id


def upload_results(client, sim_id: int) -> None:
    """The results upload the simulation worker sends at the end of a simulation"""
    payload = {"simulation_id": sim_id, "update_key": encode_simulation_auth_token(sim_id), "estimators": RESULTS}
    assert client.post("/results", json=payload).status_code == 202


def test_pages_go_to_storage_and_are_read_through_links(client, storage, sim_id):
    """The database keeps where each page is; the UI gets a link per page and the page itself is in storage"""
    upload_results(client, sim_id)

    pages = db.session.query(PageModel).all()
    assert pages
    assert all(page.compressed_data is None for page in pages)
    keys = {page.stored_object.key for page in pages}
    assert keys == set(storage)
    first = RESULTS[0]
    key = result_storage.page_key(sim_id, first["name"], int(first["pages"][0]["metadata"]["page_number"]))
    assert storage[key] == first["pages"][0]

    everything = client.get("/results", query_string={"job_id": "storagejob"}).get_json()
    some = client.get(
        "/results", query_string={"job_id": "storagejob", "estimator_name": first["name"], "page_numbers": "0"}
    ).get_json()
    for page in [page for estimator in everything["estimators"] for page in estimator["pages"]] + some["pages"]:
        assert page["url"].startswith("https://storage.test/simulations/")
        assert page["format"] == result_storage.PAGE_FORMAT


def test_pages_stay_in_the_database_without_storage(client, sim_id):
    """A deployment without a results bucket keeps working as before"""
    upload_results(client, sim_id)

    first = RESULTS[0]
    content = client.get("/results", query_string={"job_id": "storagejob", "estimator_name": first["name"]}).get_json()
    assert content["pages"][0] == first["pages"][0]


def test_deleting_a_simulation_removes_its_objects(client, storage, sim_id, monkeypatch):
    """Objects go first; if the storage fails, the simulation stays so the delete can be repeated"""
    upload_results(client, sim_id)
    removed = []
    monkeypatch.setattr(result_storage, "delete_simulation", removed.append)

    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 200
    assert removed == [sim_id]
    assert db.session.get(SimulationModel, sim_id) is None


def test_failing_storage_keeps_the_simulation(client, storage, sim_id, monkeypatch):
    """A delete that cannot remove the objects leaves the simulation in place"""
    upload_results(client, sim_id)

    def unreachable(simulation_id):
        """Storage not answering"""
        raise ConnectionError(f"storage unreachable for {simulation_id}")

    monkeypatch.setattr(result_storage, "delete_simulation", unreachable)

    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 503
    assert db.session.get(SimulationModel, sim_id) is not None


def test_pages_go_to_the_database_when_storage_fails(client, storage, sim_id, monkeypatch):
    """Results of a finished simulation are kept even if the storage is down at that moment"""
    calls = []

    def unreachable(key, page):
        """Storage not answering"""
        calls.append(key)
        raise ConnectionError(f"storage unreachable for {key}")

    monkeypatch.setattr(result_storage, "put_page", unreachable)
    upload_results(client, sim_id)

    assert len(calls) == 1  # the next pages do not wait for the storage again
    first = RESULTS[0]
    content = client.get("/results", query_string={"job_id": "storagejob", "estimator_name": first["name"]}).get_json()
    assert content["pages"][0] == first["pages"][0]
    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 200


def test_what_tasks_leave_in_storage_expires(monkeypatch):
    """The bucket removes objects under work/ itself, in case the engine's deletes miss some"""
    client = mock.Mock()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "_internal", lambda: client)
    result_storage.expire_work_objects()
    client.put_bucket_lifecycle_configuration.assert_called_once_with(
        Bucket="results",
        LifecycleConfiguration={
            "Rules": [{"ID": "work", "Filter": {"Prefix": "work/"}, "Expiration": {"Days": 2}, "Status": "Enabled"}]
        },
    )
