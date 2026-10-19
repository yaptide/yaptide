"""Results of HPC jobs: links to upload pages straight to storage, the check of what arrived, and the uploader"""

import base64
import gzip
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from yaptide.application import create_app
from yaptide.batch import results_uploader
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    ClusterModel,
    EstimatorModel,
    KeycloakUserModel,
    PageModel,
    SimulationModel,
)
from yaptide.routes.common_sim_routes import estimator_content, store_partial_results
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

MD5 = base64.b64encode(hashlib.md5(b"page").digest()).decode()
RESULTS = json.loads((Path(__file__).parent / "res" / "json_with_results.json").read_text())["estimators"]


@pytest.fixture
def client(monkeypatch):
    """Test client, a running HPC simulation with files input, and object storage kept in a dict"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    app = create_app()
    with app.app_context():
        db.create_all()
        user = KeycloakUserModel(username="plgtest")
        cluster = ClusterModel(cluster_name="ares")
        db.session.add_all([user, cluster])
        db.session.commit()
        simulation = BatchSimulationModel(
            job_id="hpcjob",
            user_id=user.id,
            cluster_id=cluster.id,
            title="hpc",
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            job_state=EntityState.MERGING_RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def storage(monkeypatch) -> dict:
    """Uploads that reached the storage: key -> (size, md5)"""
    stored = {}
    monkeypatch.setattr(
        result_storage, "upload_url", lambda key, size, md5, page=True: f"https://storage.test/{key}?signed"
    )
    monkeypatch.setattr(result_storage, "stored_matches", lambda key, size, md5: stored.get(key) == (size, md5))
    return stored


def simulation_id() -> int:
    """The HPC simulation of the test"""
    return db.session.query(SimulationModel.id).scalar()


def body(**payload) -> dict:
    """Request body of the collect job, authenticated with the simulation's update key"""
    return {"simulation_id": simulation_id(), "update_key": encode_simulation_auth_token(simulation_id()), **payload}


def listed() -> list[dict]:
    """The estimators of the test results as the uploader lists them"""
    return results_uploader.manifest([{**estimator} for estimator in RESULTS])


def store_all(storage: dict) -> None:
    """The collect job uploaded every page"""
    for estimator in listed():
        for page in estimator["pages"]:
            key = result_storage.page_key(simulation_id(), estimator["name"], page["page_number"])
            storage[key] = (page["size"], page["md5"])


def test_links_for_every_page(client, storage):
    """One signed link per page, under the simulation's own keys"""
    pages = [{"estimator": "z_profile", "page_number": 0, "size": 10, "md5": MD5}]

    response = client.post("/results/uploads", json=body(pages=pages))

    assert response.status_code == 200
    assert response.get_json()["uploads"] == [
        {
            "estimator": "z_profile",
            "page_number": 0,
            "url": f"https://storage.test/simulations/{simulation_id()}/z_profile/0.json?signed",
        }
    ]


@pytest.mark.parametrize("estimator", ["..", ".", "a/b", ""])
def test_estimator_names_cannot_leave_the_simulation(client, storage, estimator):
    """The name becomes a part of the object key, so it must be a plain name"""
    pages = [{"estimator": estimator, "page_number": 0, "size": 10, "md5": MD5}]

    assert client.post("/results/uploads", json=body(pages=pages)).status_code == 400


def test_wrong_key_and_final_simulation_are_refused(client, storage):
    """Only the simulation's own jobs, and only while it is not finished"""
    pages = [{"estimator": "z_profile", "page_number": 0, "size": 10, "md5": MD5}]
    wrong = {**body(pages=pages), "update_key": encode_simulation_auth_token(simulation_id() + 1)}
    assert client.post("/results/uploads", json=wrong).status_code == 400

    db.session.query(SimulationModel).update({"job_state": EntityState.CANCELED.value})
    db.session.commit()
    assert client.post("/results/uploads", json=body(pages=pages)).status_code == 409


def test_no_storage_tells_the_job_to_send_the_old_way(client, storage, monkeypatch):
    """501: the uploader then sends the results in one request to POST /results"""
    monkeypatch.delenv("RESULTS_S3_BUCKET")
    pages = [{"estimator": "z_profile", "page_number": 0, "size": 10, "md5": MD5}]

    assert client.post("/results/uploads", json=body(pages=pages)).status_code == 501


def test_done_lists_missing_pages_and_stores_nothing(client, storage):
    """A page not in storage (or with another size or MD5) is listed for the job to upload again"""
    store_all(storage)
    first = listed()[0]
    del storage[result_storage.page_key(simulation_id(), first["name"], first["pages"][0]["page_number"])]

    response = client.post("/results/done", json=body(estimators=listed()))

    assert response.status_code == 409
    assert response.get_json()["missing"] == [{"estimator": first["name"], "page_number": 0}]
    assert db.session.query(EstimatorModel).count() == 0


def test_done_stores_pointers_and_completes(client, storage):
    """Every page in storage: estimators and pages pointing to the objects, the simulation COMPLETED"""
    store_all(storage)

    assert client.post("/results/done", json=body(estimators=listed())).status_code == 202

    db.session.remove()
    pages = db.session.query(PageModel).all()
    assert len(pages) == sum(len(estimator["pages"]) for estimator in RESULTS)
    assert all(page.compressed_data is None and page.stored_object.key in storage for page in pages)
    assert db.session.query(SimulationModel.job_state).scalar() == EntityState.COMPLETED.value


class FakeServer(BaseHTTPRequestHandler):
    """The backend's two endpoints and the storage behind the signed links, in one server"""

    storage: dict = {}
    lost_once: set = set()
    dropped_once: set = set()
    expired_once: set = set()
    calls: list = []
    # error answers the backend gives first, e.g. while it restarts
    errors: list = []
    has_storage = True

    def do_POST(self):
        """POST /results/uploads, /results/done and the old /results"""
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeServer.calls.append(self.path)
        if FakeServer.errors:
            return self.answer(FakeServer.errors.pop(0), {})
        if self.path == "/results" or not FakeServer.has_storage:
            return self.answer(202 if self.path == "/results" else 501, {})
        if self.path == "/results/uploads":
            port = self.server.server_address[1]
            uploads = [
                {**page, "url": f"http://127.0.0.1:{port}/store/{page['estimator']}/{page['page_number']}"}
                for page in payload["pages"]
            ]
            full = [
                {"estimator": entry["estimator"], "url": f"http://127.0.0.1:{port}/store/{entry['estimator']}/full"}
                for entry in payload.get("full_resolution", [])
            ]
            return self.answer(200, {"uploads": uploads, "full_resolution_uploads": full})
        missing = [
            {"estimator": estimator["name"], "page_number": page["page_number"]}
            for estimator in payload["estimators"]
            for page in estimator["pages"]
            if FakeServer.storage.get(f"{estimator['name']}/{page['page_number']}") != (page["size"], page["md5"])
        ]
        missing += [
            {"estimator": estimator["name"], "full_resolution": True}
            for estimator in payload["estimators"]
            if "full_resolution" in estimator
            and FakeServer.storage.get(f"{estimator['name']}/full")
            != (estimator["full_resolution"]["size"], estimator["full_resolution"]["md5"])
        ]
        return self.answer(409, {"missing": missing}) if missing else self.answer(202, {})

    def do_PUT(self):
        """The storage: refuses a body whose MD5 differs from the signed one; the first upload of a page may get lost"""
        data = self.rfile.read(int(self.headers["Content-Length"]))
        key = self.path.removeprefix("/store/")
        if key in FakeServer.dropped_once:
            # the connection breaks without an answer, e.g. nginx restarting
            FakeServer.dropped_once.discard(key)
            self.close_connection = True
            return None
        if key in FakeServer.expired_once:
            FakeServer.expired_once.discard(key)
            return self.answer(403, {})
        if base64.b64encode(hashlib.md5(data).digest()).decode() != self.headers["Content-MD5"]:
            return self.answer(400, {})
        if key in FakeServer.lost_once:
            FakeServer.lost_once.discard(key)
        else:
            FakeServer.storage[key] = (len(data), self.headers["Content-MD5"])
        return self.answer(200, {})

    def answer(self, code: int, content: dict) -> None:
        """JSON answer"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(content).encode())

    def log_message(self, *_):  # skipcq: PYL-R0201
        """Keeps the test output quiet"""


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    """The fake backend and storage, and the collect job's output directory with convertmc's files"""
    FakeServer.storage, FakeServer.lost_once, FakeServer.calls, FakeServer.has_storage = {}, set(), [], True
    FakeServer.dropped_once, FakeServer.expired_once, FakeServer.errors = set(), set(), []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for estimator in RESULTS:
        (tmp_path / f"{estimator['name']}.json").write_text(
            json.dumps({k: v for k, v in estimator.items() if k != "name"})
        )
    monkeypatch.setattr(results_uploader, "RETRY_SECONDS", 0)
    yield SimpleNamespace(
        output_dir=str(tmp_path), sim_id=1, update_key="key", backend_url=f"http://127.0.0.1:{server.server_address[1]}"
    )
    server.shutdown()


def test_uploader_uploads_every_page_and_reports_done(fake_server):
    """Every page arrives as the gzipped page JSON, then the job is done"""
    assert results_uploader.main(fake_server) == 0

    assert len(FakeServer.storage) == sum(len(estimator["pages"]) for estimator in RESULTS)
    assert FakeServer.calls == ["/results/uploads", "/results/done"]
    page = RESULTS[0]["pages"][0]
    assert gzip.decompress(results_uploader.page_body(page)) == json.dumps(page).encode()


def test_uploader_uploads_missing_pages_again(fake_server):
    """A page the storage lost is uploaded again, only that one"""
    first = RESULTS[0]
    FakeServer.lost_once = {f"{first['name']}/{first['pages'][0]['metadata']['page_number']}"}

    assert results_uploader.main(fake_server) == 0

    assert FakeServer.calls == ["/results/uploads", "/results/done", "/results/uploads", "/results/done"]


def test_uploader_sends_the_old_way_without_storage(fake_server):
    """A backend without object storage gets the results in one request"""
    FakeServer.has_storage = False

    assert results_uploader.main(fake_server) == 0

    assert FakeServer.calls == ["/results/uploads", "/results"]


def first_page_key() -> str:
    """The fake storage's key of the first page"""
    return f"{RESULTS[0]['name']}/{RESULTS[0]['pages'][0]['metadata']['page_number']}"


def test_uploader_survives_a_dropped_connection(fake_server):
    """A connection broken during an upload is retried, not the end of the simulation"""
    FakeServer.dropped_once = {first_page_key()}

    assert results_uploader.main(fake_server) == 0

    assert len(FakeServer.storage) == sum(len(estimator["pages"]) for estimator in RESULTS)


def test_uploader_gets_new_links_when_one_expires(fake_server):
    """A refused (expired) link makes the uploader ask for new links for what is left"""
    FakeServer.expired_once = {first_page_key()}

    assert results_uploader.main(fake_server) == 0

    assert FakeServer.calls == ["/results/uploads", "/results/uploads", "/results/done"]


def test_uploader_waits_out_a_restart_of_several_minutes(fake_server, monkeypatch):
    """Transient errors are retried with doubling pauses, about a quarter of an hour in all"""
    FakeServer.errors = [502, 503, 429, 504] * 2 + [503, 502]
    pauses = []
    # only the uploader's own pauses: replacing time.sleep for the process makes other threads spin
    monkeypatch.setattr(results_uploader, "time", SimpleNamespace(sleep=pauses.append))
    monkeypatch.setattr(results_uploader, "RETRY_SECONDS", 5)

    assert results_uploader.main(fake_server) == 0

    assert pauses == [5, 10, 20, 40, 80, 120, 120, 120, 120, 120]
    all_pauses = [min(5 * 2**attempt, 120) for attempt in range(results_uploader.ATTEMPTS - 1)]
    assert 10 * 60 <= sum(all_pauses) <= 15 * 60


def test_uploader_does_not_retry_a_refusal(fake_server, monkeypatch):
    """A 4xx answer, e.g. 409 for a simulation already in a final state, ends the upload at once"""
    FakeServer.errors = [409]
    pauses = []
    # only the uploader's own pauses: replacing time.sleep for the process makes other threads spin
    monkeypatch.setattr(results_uploader, "time", SimpleNamespace(sleep=pauses.append))

    assert results_uploader.main(fake_server) == 1

    assert FakeServer.calls == ["/results/uploads"]
    assert not pauses


def test_no_partial_results_once_the_final_pages_are_uploaded(client, storage):
    """The engine's partial results go to the same pages as the final ones: none is stored after the links for the
    final ones were handed out
    """
    db.session.query(SimulationModel).update({"job_state": EntityState.RUNNING.value})
    db.session.commit()
    pages = [{"estimator": "z_profile", "page_number": 0, "size": 10, "md5": MD5}]

    assert client.post("/results/uploads", json=body(pages=pages)).status_code == 200

    db.session.remove()
    simulation = db.session.get(SimulationModel, simulation_id())
    assert simulation.job_state == EntityState.MERGING_RUNNING.value
    assert not store_partial_results(simulation, RESULTS, 100)


def test_uploader_uploads_the_full_resolution_next_to_the_pages(fake_server):
    """A .bdo file next to an estimator's JSON is uploaded as it is, checked like the pages; a lost one again"""
    name = RESULTS[0]["name"]
    full = Path(fake_server.output_dir) / f"{name}.bdo"
    full.write_bytes(b"full resolution " * 1000)
    FakeServer.lost_once = {f"{name}/full"}

    assert results_uploader.main(fake_server) == 0

    md5 = base64.b64encode(hashlib.md5(full.read_bytes()).digest()).decode()
    assert FakeServer.storage[f"{name}/full"] == (16000, md5)
    assert FakeServer.calls == ["/results/uploads", "/results/done", "/results/uploads", "/results/done"]


def test_uploader_skips_a_full_resolution_too_large_for_a_link(fake_server, monkeypatch):
    """Larger than nginx lets through: the results go without it"""
    (Path(fake_server.output_dir) / f"{RESULTS[0]['name']}.bdo").write_bytes(b"full" * 1000)
    monkeypatch.setattr(results_uploader, "MAX_FULL_RESOLUTION_BYTES", 100)

    assert results_uploader.main(fake_server) == 0

    assert not [key for key in FakeServer.storage if key.endswith("/full")]


def test_full_resolution_link_check_and_store(client, storage):
    """A link for the full resolution under the estimator's pages; the results are stored once it is in storage"""
    name = RESULTS[0]["name"]
    full = {"estimator": name, "size": 5000, "md5": MD5}
    pages = [{"estimator": name, "page_number": 0, "size": 10, "md5": MD5}]

    response = client.post("/results/uploads", json=body(pages=pages, full_resolution=[full]))

    key = result_storage.full_resolution_key(simulation_id(), name)
    assert response.get_json()["full_resolution_uploads"] == [
        {"estimator": name, "url": f"https://storage.test/{key}?signed"}
    ]
    store_all(storage)
    estimators = listed()
    estimators[0]["full_resolution"] = {"size": 5000, "md5": MD5}
    done = client.post("/results/done", json=body(estimators=estimators))
    assert done.status_code == 409
    assert done.get_json()["missing"] == [{"estimator": name, "full_resolution": True}]

    storage[key] = (5000, MD5)
    assert client.post("/results/done", json=body(estimators=estimators)).status_code == 202
    db.session.remove()
    stored = db.session.query(EstimatorModel).filter_by(file_name=name).one()
    assert stored.data["full_resolution"] is True


def test_metadata_cannot_claim_a_full_resolution(client, storage, monkeypatch):
    """A full resolution in a job's metadata, here pointing at another simulation's page, is dropped"""
    monkeypatch.setattr(result_storage, "page_url", lambda key: f"https://storage.test/{key}?signed")
    store_all(storage)
    estimators = listed()
    forged = {"key": "simulations/999/secret/0.json", "size": 1}
    estimators[0]["metadata"] = {**estimators[0]["metadata"], "full_resolution": forged}

    assert client.post("/results/done", json=body(estimators=estimators)).status_code == 202

    db.session.remove()
    stored = db.session.query(EstimatorModel).filter_by(file_name=estimators[0]["name"]).one()
    assert "full_resolution" not in stored.data
    assert "full_resolution" not in estimator_content(stored, stored.pages)


def test_full_resolution_entries_are_checked(client, storage):
    """A full resolution larger than a link uploads, or with a bad name, is refused"""
    pages = [{"estimator": "z_profile", "page_number": 0, "size": 10, "md5": MD5}]
    too_large = {"estimator": "z_profile", "size": results_uploader.MAX_FULL_RESOLUTION_BYTES + 1, "md5": MD5}
    bad_name = {"estimator": "../x", "size": 10, "md5": MD5}

    for full in (too_large, bad_name):
        assert client.post("/results/uploads", json=body(pages=pages, full_resolution=[full])).status_code == 400
