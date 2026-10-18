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


def test_deleting_a_simulation_does_not_wait_for_the_storage(client, storage, sim_id, monkeypatch):
    """The simulation goes at once, also with the storage down; the engine removes its objects afterwards"""
    upload_results(client, sim_id)
    db.session.get(SimulationModel, sim_id).job_state = EntityState.COMPLETED.value
    db.session.commit()

    def unreachable(*args):
        """Storage not answering"""
        raise ConnectionError(f"storage unreachable for {args}")

    monkeypatch.setattr(result_storage, "_client", unreachable)

    assert client.delete("/user/simulations", query_string={"job_id": "storagejob"}).status_code == 200
    assert db.session.get(SimulationModel, sim_id) is None


def test_objects_are_removed_in_batches_as_they_are_listed(monkeypatch):
    """Each listed batch of a simulation's directories goes in one request, with the client given time and retries;
    the result pages only when asked for
    """
    client = mock.Mock()
    listings = {
        "simulations/7/": [{"Contents": [{"Key": "simulations/7/a/0.json"}]}],
        "hpc/7/": [{"Contents": [{"Key": f"hpc/7/progress/task_{i}.json"} for i in range(3)]}, {"Contents": []}],
        "work/7/": [{}],
    }
    client.get_paginator.return_value.paginate.side_effect = lambda **kwargs: listings[kwargs["Prefix"]]
    client.delete_objects.return_value = {}
    clients = []
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setenv("RESULTS_S3_ENDPOINT", "http://garage:3900")
    monkeypatch.setattr(result_storage, "_client", lambda *args, **kwargs: clients.append(kwargs) or client)

    result_storage.delete_simulation(7, pages=False)
    assert "simulations/7/" not in str(client.get_paginator.return_value.paginate.call_args_list)
    result_storage.delete_simulation(7, pages=True)

    assert {"read_timeout": 120, "attempts": 5} in clients
    for call in client.get_paginator.return_value.paginate.call_args_list:
        assert call.kwargs["PaginationConfig"] == {"PageSize": result_storage.DELETE_BATCH}
    progress = [{"Key": f"hpc/7/progress/task_{i}.json"} for i in range(3)]
    assert [call.kwargs["Delete"]["Objects"] for call in client.delete_objects.call_args_list] == [
        progress,
        [{"Key": "simulations/7/a/0.json"}],
        progress,
    ]

    client.delete_objects.return_value = {"Errors": [{"Key": "hpc/7/progress/task_0.json"}]}
    with pytest.raises(RuntimeError):
        result_storage.delete_simulation(7, pages=False)


def test_a_task_removes_its_save_with_the_fast_client(monkeypatch):
    """A cancelled task does not wait minutes for a busy storage"""
    clients = []
    client = mock.Mock()
    client.get_paginator.return_value.paginate.return_value = [{}]
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setenv("RESULTS_S3_ENDPOINT", "http://garage:3900")
    monkeypatch.setattr(result_storage, "_client", lambda *args, **kwargs: clients.append(kwargs) or client)

    result_storage.delete_objects(result_storage.work_key(7, 1))

    assert clients == [{}]


def test_stored_simulations_come_from_the_directory_names_never_of_pages(monkeypatch):
    """Only directories named by a simulation id count, and only where nothing is the only copy of results"""
    client = mock.Mock()
    listings = {
        "hpc/": [{"CommonPrefixes": [{"Prefix": "hpc/12/"}, {"Prefix": "hpc/3/"}, {"Prefix": "hpc/x/"}]}],
        "work/": [{"CommonPrefixes": [{"Prefix": "work/5/"}]}],
    }
    client.get_paginator.return_value.paginate.side_effect = lambda **kwargs: listings[kwargs["Prefix"]]
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "_internal", lambda: client)

    assert result_storage.stored_simulations() == {3, 5, 12}
    assert result_storage.page_key(3, "dose", 0).startswith(result_storage.PAGE_PREFIX)
    assert result_storage.PAGE_PREFIX not in result_storage.EPHEMERAL_PREFIXES


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


def test_what_tasks_and_hpc_jobs_leave_in_storage_expires(monkeypatch):
    """The bucket removes objects under work/ and hpc/ itself, in case the engine's deletes miss some; one call sets
    all the rules
    """
    client = mock.Mock()
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "_internal", lambda: client)
    result_storage.expire_objects()
    client.put_bucket_lifecycle_configuration.assert_called_once_with(
        Bucket="results",
        LifecycleConfiguration={
            "Rules": [
                {"ID": "work", "Filter": {"Prefix": "work/"}, "Expiration": {"Days": 2}, "Status": "Enabled"},
                {"ID": "hpc", "Filter": {"Prefix": "hpc/"}, "Expiration": {"Days": 14}, "Status": "Enabled"},
            ]
        },
    )


def test_job_links_let_each_task_put_only_its_own_save(monkeypatch):
    """A PUT link per saving task, for its work key only, at the public address and lasting as long as the others"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setenv("RESULTS_S3_PUBLIC_ENDPOINT", "https://yaptide.test")
    monkeypatch.setenv("RESULTS_S3_ACCESS_KEY", "GK0")
    monkeypatch.setenv("RESULTS_S3_SECRET_KEY", "secret")
    result_storage._client.cache_clear()  # skipcq: PYL-W0212

    links = result_storage.job_links(5, saving_tasks=2)
    result_storage._client.cache_clear()  # skipcq: PYL-W0212

    urls = links["saves"]["urls"]
    assert sorted(urls) == ["1", "2"] and links["saves"]["max_bytes"] == result_storage.HPC_SAVES_MAX_BYTES // 2
    for task, url in urls.items():
        assert url.startswith(f"https://yaptide.test/results/work/5/task_{task}.tar.gz?")
        assert f"X-Amz-Expires={result_storage.JOB_LINK_SECONDS}" in url


def listing_page(keys: list[str], token: str = "") -> bytes:
    """A ListObjectsV2 answer of the storage"""
    items = "".join(f"<Contents><Key>{key}</Key><ETag>&quot;{key[-6]}&quot;</ETag></Contents>" for key in keys)
    next_token = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    xmlns = "http://s3.amazonaws.com/doc/2006-03-01/"
    return f'<ListBucketResult xmlns="{xmlns}">{items}{next_token}</ListBucketResult>'.encode()


def test_progress_reports_are_listed_and_read_with_signed_gets(monkeypatch):
    """The reports are listed page by page and read with plain signed GETs; storage answering an error raises
    ConnectionError, which ends the engine's round
    """
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setenv("RESULTS_S3_ENDPOINT", "http://garage:3900")
    monkeypatch.setenv("RESULTS_S3_ACCESS_KEY", "GK1")
    monkeypatch.setenv("RESULTS_S3_SECRET_KEY", "secret")
    result_storage._report_reader.cache_clear()  # skipcq: PYL-W0212
    pages = [listing_page(["hpc/7/progress/task_0001.json"], "next"), listing_page(["hpc/7/progress/task_0002.json"])]
    answers = [mock.Mock(status=200, data=page) for page in pages]
    answers.append(mock.Mock(status=200, data=b'{"update": {"task_state": "RUNNING"}}'))
    answers.append(mock.Mock(status=503, data=b""))
    request = mock.Mock(side_effect=answers)
    monkeypatch.setattr(result_storage._report_reader()[1], "request", request)  # skipcq: PYL-W0212

    assert result_storage.progress_reports(7) == {
        "hpc/7/progress/task_0001.json": '"1"',
        "hpc/7/progress/task_0002.json": '"2"',
    }
    assert result_storage.read_report("hpc/7/progress/task_0001.json") == {"update": {"task_state": "RUNNING"}}
    with pytest.raises(ConnectionError):
        result_storage.read_report("hpc/7/progress/task_0002.json")

    urls = [call.args[1] for call in request.call_args_list]
    assert urls[0] == "http://garage:3900/results?list-type=2&prefix=hpc%2F7%2Fprogress%2F"
    assert urls[1].endswith("&continuation-token=next")
    assert urls[2] == "http://garage:3900/results/hpc/7/progress/task_0001.json"
    assert all(
        "AWS4-HMAC-SHA256 Credential=GK1/" in call.kwargs["headers"]["Authorization"] for call in request.call_args_list
    )
    result_storage._report_reader.cache_clear()  # skipcq: PYL-W0212
