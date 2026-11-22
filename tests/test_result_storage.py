"""Result pages in object storage: written there when results arrive, read through signed links, removed with the
simulation. Run against the bucket of tests/conftest.py (an S3 mock, or the server RESULTS_S3_ENDPOINT points at)
"""

import json
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from yaptide.application import create_app
from yaptide.batch import result_format
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    CelerySimulationModel,
    EstimatorModel,
    PageModel,
    PageObjectModel,
    SimulationModel,
    YaptideUserModel,
)
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


def new_simulation(client, job_id: str) -> int:
    """Running direct simulation of a logged in user, with input given as files"""
    user = db.session.query(YaptideUserModel).first()
    if user is None:
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
    simulation = CelerySimulationModel(
        job_id=job_id,
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


@pytest.fixture
def sim_id(client) -> int:
    """Running direct simulation of a logged in user"""
    return new_simulation(client, "storagejob")


def upload_results(client, sim_id: int, estimators: list = RESULTS) -> int:
    """The results upload a merge sends at the end of a simulation; returns the status code"""
    payload = {"simulation_id": sim_id, "update_key": encode_simulation_auth_token(sim_id), "estimators": estimators}
    return client.post("/results", json=payload).status_code


def stored_keys(sim_id: int) -> set[str]:
    """Keys of every object in the bucket under the simulation's pages"""
    listing = result_storage._internal().list_objects_v2(  # skipcq: PYL-W0212
        Bucket=result_storage.bucket(), Prefix=f"{result_storage.PAGE_PREFIX}{sim_id}/"
    )
    return {item["Key"] for item in listing.get("Contents", [])}


def stored_page(prefix: str) -> dict:
    """A page in storage read back as the JSON page it was made from"""
    return result_format.json_page(*result_format.read_page(result_storage.get_page_files(prefix)))


def assert_same_page(page: dict, expected: dict) -> None:
    """The page with its values as float32"""
    page, expected = json.loads(json.dumps(page)), json.loads(json.dumps(expected))
    values, expected_values = page["data"].pop("values"), expected["data"].pop("values")
    np.testing.assert_allclose(values, expected_values, rtol=1e-6)
    assert page == expected


def test_pages_go_to_storage_and_the_database_keeps_where(client, sim_id):
    """Every page is a Zarr array in the bucket under a prefix of its own; the database has no page data"""
    assert upload_results(client, sim_id) == 202

    pages = db.session.query(PageModel).all()
    assert len(pages) == sum(len(estimator["pages"]) for estimator in RESULTS)
    assert all(page.compressed_data is None for page in pages)
    assert all(page.stored_object.format == result_storage.ZARR_FORMAT for page in pages)
    prefixes = {page.stored_object.key for page in pages}
    assert {key.removesuffix(result_format.METADATA_FILE) for key in stored_keys(sim_id) if key.endswith(".json")} == (
        prefixes
    )
    for page in pages:
        assert page.stored_object.size == sum(
            len(body) for body in result_storage.get_page_files(page.stored_object.key).values()
        )
    for estimator in RESULTS:
        for expected in estimator["pages"]:
            number = int(expected["metadata"]["page_number"])
            (prefix,) = [
                key for key in prefixes if key.startswith(f"simulations/{sim_id}/{estimator['name']}/{number}/")
            ]
            assert_same_page(stored_page(prefix), expected)
    assert simulation_state(sim_id) == EntityState.COMPLETED.value


def simulation_state(sim_id: int) -> str:
    """The simulation's state in the database"""
    db.session.expire_all()
    return db.session.get(SimulationModel, sim_id).job_state


def test_results_answer_with_signed_links_to_every_object(client, sim_id):
    """All results, one estimator, one page and some pages: each page as links, never its values"""
    upload_results(client, sim_id)
    first = RESULTS[0]
    queries = [
        {},
        {"estimator_name": first["name"]},
        {"estimator_name": first["name"], "page_number": 0},
        {"estimator_name": first["name"], "page_numbers": "0-1"},
    ]
    answers = [client.get("/results", query_string={"job_id": "storagejob", **query}).get_json() for query in queries]
    pages = [page for estimator in answers[0]["estimators"] for page in estimator["pages"]]
    pages += answers[1]["pages"] + [answers[2]["page"]] + answers[3]["pages"]

    assert len(pages) == sum(len(estimator["pages"]) for estimator in RESULTS) + len(first["pages"]) + 1 + 2
    for page in pages:
        assert page["format"] == result_storage.ZARR_FORMAT
        assert set(page["files"]) == set(result_format.FILES)
        assert page["url"] == page["files"][result_format.METADATA_FILE]
        assert page["url"].startswith(f"https://yaptide.test/{result_storage.bucket()}/simulations/{sim_id}/")
        assert "X-Amz-Signature=" in page["url"] and f"X-Amz-Expires={result_storage.URL_SECONDS}" in page["url"]
        assert {"page_number", "name", "dimensions"} <= set(page)
        assert "data" not in page


def test_a_signed_link_reads_the_object(client, sim_id, monkeypatch):
    """The links work: signed for the public address, fetched there (here the storage itself) without credentials"""
    upload_results(client, sim_id)
    monkeypatch.setenv("RESULTS_S3_PUBLIC_ENDPOINT", result_storage.os.environ["RESULTS_S3_ENDPOINT"])
    page = db.session.query(PageModel).filter(PageModel.page_dimension == 2).first()
    files = result_storage.page_file_urls(page.stored_object.key)

    fetched = {}
    for name, url in files.items():
        with urllib.request.urlopen(url, timeout=10) as answer:  # skipcq: BAN-B310
            fetched[name] = answer.read()

    assert fetched == result_storage.get_page_files(page.stored_object.key)
    assert result_format.read_page(fetched)[0]["dimensions"] == 2


def test_results_stored_again_replace_the_pages_and_remove_the_old_ones(client, sim_id):
    """A repeated upload stores the pages under a new revision and removes the previous one once committed"""
    upload_results(client, sim_id)
    before = {page.id: page.stored_object.key for page in db.session.query(PageModel)}
    keys_before = stored_keys(sim_id)

    assert upload_results(client, sim_id) == 202

    db.session.expire_all()
    after = {page.id: page.stored_object.key for page in db.session.query(PageModel)}
    assert after.keys() == before.keys()
    assert all(after[page_id] != before[page_id] for page_id in before)
    assert len(stored_keys(sim_id)) == len(keys_before)
    assert not stored_keys(sim_id) & keys_before


def test_storage_failure_keeps_nothing(client, sim_id, monkeypatch):
    """Storage failing half way: no estimators or pages in the database, no objects left, the merge told so"""
    real_put = result_storage.put_page_files
    calls = []

    def failing_put(prefix: str, files: dict) -> int:
        """Stores two pages, then the storage stops answering"""
        calls.append(prefix)
        if len(calls) > 2:
            raise ConnectionError(f"storage unreachable for {prefix}")
        return real_put(prefix, files)

    monkeypatch.setattr(result_storage, "put_page_files", failing_put)

    assert upload_results(client, sim_id) == 500

    assert db.session.query(EstimatorModel).count() == 0
    assert db.session.query(PageModel).count() == 0
    assert stored_keys(sim_id) == set()
    assert simulation_state(sim_id) == EntityState.RUNNING.value


def test_pages_stored_before_the_bucket_are_still_served(client, sim_id):
    """A page with its data in the database (not moved yet) goes to the UI as it is"""
    estimator = EstimatorModel(name="old", file_name="old", simulation_id=sim_id)
    estimator.data = RESULTS[2]["metadata"]
    db.session.add(estimator)
    db.session.commit()
    expected = RESULTS[2]["pages"][0]
    page = PageModel(estimator_id=estimator.id, page_number=0, page_dimension=1, page_name="dose")
    page.data = expected
    db.session.add(page)
    db.session.commit()

    answer = client.get("/results", query_string={"job_id": "storagejob", "estimator_name": "old"}).get_json()

    assert answer["pages"] == [expected]


def test_a_page_without_values_has_no_shard(client, sim_id):
    """An empty page is only its zarr.json; it reads back empty, and its shard's link is still handed out"""
    estimator = json.loads(json.dumps(RESULTS[1]))
    estimator["pages"] = [estimator["pages"][0]]
    estimator["pages"][0]["data"]["values"] = []

    assert upload_results(client, sim_id, [estimator]) == 202

    (page,) = db.session.query(PageModel).all()
    assert stored_keys(sim_id) == {page.stored_object.key + result_format.METADATA_FILE}
    assert result_format.read_page(result_storage.get_page_files(page.stored_object.key))[1] == []
    answer = client.get("/results", query_string={"job_id": "storagejob"}).get_json()
    assert set(answer["estimators"][0]["pages"][0]["files"]) == set(result_format.FILES)


def test_deleting_a_simulation_removes_its_objects_only(client, sim_id):
    """The deleted simulation's pages go from the bucket, another simulation's stay"""
    other = new_simulation(client, "otherjob")
    upload_results(client, sim_id)
    upload_results(client, other)
    other_keys = stored_keys(other)

    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 200

    assert db.session.get(SimulationModel, sim_id) is None
    assert db.session.query(PageObjectModel).count() == len(db.session.query(PageModel).all())
    assert stored_keys(sim_id) == set()
    assert stored_keys(other) == other_keys and other_keys


def test_deleting_a_simulation_does_not_wait_for_the_storage(client, sim_id, monkeypatch):
    """The simulation goes also with the storage down; its objects stay, nobody reads them"""
    upload_results(client, sim_id)

    def unreachable(*args, **kwargs):
        """Storage not answering"""
        raise ConnectionError(f"storage unreachable for {args}")

    monkeypatch.setattr(result_storage, "_client", unreachable)

    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 200
    assert db.session.get(SimulationModel, sim_id) is None


def test_objects_are_removed_in_batches_as_they_are_listed(monkeypatch):
    """Each listed batch goes in one request, with the client given time and retries; a refused key raises"""
    client = mock.Mock()
    keys = [{"Key": f"simulations/7/dose/{i}/0123456789abcdef/zarr.json"} for i in range(3)]
    client.get_paginator.return_value.paginate.return_value = [{"Contents": keys[:2]}, {"Contents": keys[2:]}, {}]
    client.delete_objects.return_value = {}
    clients = []
    monkeypatch.setattr(result_storage, "_client", lambda *args, **kwargs: clients.append(kwargs) or client)

    result_storage.delete_simulation(7)

    assert clients == [{"read_timeout": 120, "attempts": 5}]
    paginate = client.get_paginator.return_value.paginate
    assert paginate.call_args.kwargs["Prefix"] == "simulations/7/"
    assert paginate.call_args.kwargs["PaginationConfig"] == {"PageSize": result_storage.DELETE_BATCH}
    assert [call.kwargs["Delete"]["Objects"] for call in client.delete_objects.call_args_list] == [keys[:2], keys[2:]]

    client.delete_objects.return_value = {"Errors": [keys[0]]}
    with pytest.raises(RuntimeError):
        result_storage.delete_simulation(7)


def test_the_backend_needs_the_bucket(monkeypatch):
    """Without the bucket's settings the app does not start, and says which are missing"""
    monkeypatch.delenv("RESULTS_S3_BUCKET")
    monkeypatch.setenv("RESULTS_S3_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="RESULTS_S3_BUCKET, RESULTS_S3_SECRET_KEY"):
        create_app()
