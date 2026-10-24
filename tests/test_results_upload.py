"""Results of HPC jobs: links to upload pages straight to storage, the check of what arrived, and the uploader

The cluster uploads pages in ZARR_FORMAT (two objects each, under a revision); a job submitted before uploads gzipped
JSON pages (one object each), which the backend still takes.
"""

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
from yaptide.batch import result_format, results_uploader
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
from yaptide.batch import results_merger
from yaptide.routes.common_sim_routes import store_partial_results
from yaptide.routes.utils.tokens import encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

MD5 = base64.b64encode(hashlib.md5(b"page").digest()).decode()
RESULTS = json.loads((Path(__file__).parent / "res" / "json_with_results.json").read_text())["estimators"]
BDO_DIR = Path(__file__).parent / "res" / "bdo"


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
        result_storage, "upload_url", lambda key, size, md5, *args: f"https://storage.test/{key}?signed"
    )
    monkeypatch.setattr(result_storage, "stored_matches", lambda key, size, md5: stored.get(key) == (size, md5))
    monkeypatch.setattr(
        result_storage,
        "delete_pages",
        lambda prefixes: [stored.pop(key) for key in list(stored) if any(key.startswith(p) for p in prefixes)],
    )
    return stored


def simulation_id() -> int:
    """The HPC simulation of the test"""
    return db.session.query(SimulationModel.id).scalar()


def body(**payload) -> dict:
    """Request body of the collect job, authenticated with the simulation's update key"""
    return {"simulation_id": simulation_id(), "update_key": encode_simulation_auth_token(simulation_id()), **payload}


def legacy_body(page: dict) -> bytes:
    """A page as a job submitted before uploads it: gzipped JSON"""
    return gzip.compress(json.dumps(page).encode(), mtime=0)


def listed() -> list[dict]:
    """The estimators of the test results as a job submitted before lists them: size and md5 of each page"""
    return [
        {
            "name": estimator["name"],
            "metadata": estimator["metadata"],
            "pages": [
                {
                    "page_number": int(page["metadata"]["page_number"]),
                    "name": page["metadata"]["name"],
                    "dimensions": page["dimensions"],
                    "size": len(legacy_body(page)),
                    "md5": result_format.body_md5(legacy_body(page)),
                }
                for page in estimator["pages"]
            ],
        }
        for estimator in RESULTS
    ]


def store_all(storage: dict) -> None:
    """The collect job uploaded every page"""
    for estimator in listed():
        for page in estimator["pages"]:
            key = result_storage.page_key(simulation_id(), estimator["name"], page["page_number"])
            storage[key] = (page["size"], page["md5"])


REVISION = "0123456789abcdef"


def zarr_listed(tmp_path: Path) -> list[dict]:
    """The estimators of the test results as the uploader lists them after results_merger.py: the objects of each
    page
    """
    manifest, _ = results_uploader.from_convertmc(write_convertmc(tmp_path))
    return manifest["estimators"]


def write_convertmc(directory: Path) -> Path:
    """convertmc's output of the test results: one JSON file per estimator"""
    directory.mkdir(parents=True, exist_ok=True)
    for estimator in RESULTS:
        (directory / f"{estimator['name']}.json").write_text(
            json.dumps({k: v for k, v in estimator.items() if k != "name"})
        )
    return directory


def store_all_zarr(storage: dict, estimators: list[dict]) -> None:
    """The cluster uploaded every object of every page under REVISION"""
    for estimator in estimators:
        for page in estimator["pages"]:
            prefix = result_storage.page_prefix(simulation_id(), estimator["name"], page["page_number"], REVISION)
            for name, entry in page["files"].items():
                storage[prefix + name] = (entry["size"], entry["md5"])


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
    assert {page.stored_object.format for page in pages} == {result_storage.PAGE_FORMAT}
    assert db.session.query(SimulationModel.job_state).scalar() == EntityState.COMPLETED.value


def test_links_for_every_object_of_a_zarr_page(client, storage):
    """A page in ZARR_FORMAT gets a link per object, under a revision the answer names and the job sends back"""
    pages = [{"estimator": "z_profile", "page_number": 0, "files": {"zarr.json": {"size": 10, "md5": MD5}}}]

    answer = client.post("/results/uploads", json=body(pages=pages)).get_json()

    revision = answer["revision"]
    assert result_storage.REVISION_PATTERN.fullmatch(revision)
    prefix = f"https://storage.test/simulations/{simulation_id()}/z_profile/0/{revision}/"
    assert answer["uploads"] == [
        {"estimator": "z_profile", "page_number": 0, "files": {"zarr.json": prefix + "zarr.json?signed"}}
    ]
    again = client.post("/results/uploads", json=body(pages=pages, revision=revision)).get_json()
    assert again["revision"] == revision
    assert client.post("/results/uploads", json=body(pages=pages, revision="../x")).status_code == 400


@pytest.mark.parametrize(
    "files", [{}, {"c/0": {"size": 1, "md5": MD5}}, {"zarr.json": {"size": 1, "md5": MD5}, "x": {}}]
)
def test_zarr_pages_list_their_own_objects_only(client, storage, files):
    """A page has its metadata object, and nothing but the format's objects"""
    pages = [{"estimator": "z_profile", "page_number": 0, "files": files}]

    assert client.post("/results/uploads", json=body(pages=pages)).status_code == 400


def test_done_stores_zarr_pages_and_completes(client, storage, tmp_path):
    """Every object in storage: pages pointing to their prefix in ZARR_FORMAT; a missing object lists its page"""
    estimators = zarr_listed(tmp_path)
    store_all_zarr(storage, estimators)
    first = estimators[0]
    prefix = result_storage.page_prefix(simulation_id(), first["name"], 0, REVISION)
    kept = storage.pop(prefix + "c/0")

    response = client.post("/results/done", json=body(estimators=estimators, revision=REVISION))
    assert response.status_code == 409 and response.get_json()["missing"] == [
        {"estimator": first["name"], "page_number": 0}
    ]

    storage[prefix + "c/0"] = kept
    assert client.post("/results/done", json=body(estimators=estimators)).status_code == 400  # without the revision
    assert client.post("/results/done", json=body(estimators=estimators, revision=REVISION)).status_code == 202

    db.session.remove()
    pages = db.session.query(PageModel).all()
    assert len(pages) == sum(len(estimator["pages"]) for estimator in RESULTS)
    assert {page.stored_object.format for page in pages} == {result_storage.ZARR_FORMAT}
    assert all(page.stored_object.key + "zarr.json" in storage for page in pages)
    assert db.session.query(SimulationModel.job_state).scalar() == EntityState.COMPLETED.value


def test_partial_results_from_the_cluster(client, storage, tmp_path):
    """Partial results the cluster merged are stored while the simulation runs, without changing its state; the
    pages they replace are removed. Once it no longer runs they are refused and their objects removed
    """
    db.session.query(SimulationModel).update({"job_state": EntityState.RUNNING.value})
    db.session.commit()
    estimators = zarr_listed(tmp_path)
    store_all_zarr(storage, estimators)
    entries = [
        {"estimator": estimator["name"], "page_number": page["page_number"], "files": page["files"]}
        for estimator in estimators
        for page in estimator["pages"]
    ]

    assert client.post("/results/uploads", json=body(pages=entries, partial=True)).status_code == 200
    partial = body(estimators=estimators, revision=REVISION, partial=True)
    assert client.post("/results/done", json=partial).status_code == 400  # without the primaries
    assert client.post("/results/done", json=dict(partial, primaries=300)).status_code == 202

    db.session.remove()
    simulation = db.session.get(SimulationModel, simulation_id())
    assert simulation.job_state == EntityState.RUNNING.value and simulation.partial_primaries == 300
    first_keys = {page.stored_object.key for page in db.session.query(PageModel).all()}

    newer = "fedcba9876543210"
    for key, value in list(storage.items()):
        storage[key.replace(REVISION, newer)] = value
    assert client.post("/results/done", json=dict(partial, primaries=600, revision=newer)).status_code == 202
    assert not any(REVISION in key for key in storage)  # the older pages went
    assert all(newer in page.stored_object.key for page in db.session.query(PageModel).all())
    assert first_keys

    db.session.query(SimulationModel).update({"job_state": EntityState.MERGING_RUNNING.value})
    db.session.commit()
    assert client.post("/results/uploads", json=body(pages=entries, partial=True)).status_code == 409
    newest = "00000000000000ff"
    for key, value in list(storage.items()):
        storage[key.replace(newer, newest)] = value
    assert client.post("/results/done", json=dict(partial, primaries=900, revision=newest)).status_code == 409
    assert not any(newest in key for key in storage)


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
    payloads: list = []

    def do_POST(self):
        """POST /results/uploads, /results/done and the old /results"""
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeServer.calls.append(self.path)
        FakeServer.payloads.append(payload)
        if FakeServer.errors:
            return self.answer(FakeServer.errors.pop(0), {})
        if self.path == "/results" or not FakeServer.has_storage:
            return self.answer(202 if self.path == "/results" else 501, {})
        if self.path == "/results/uploads":
            port = self.server.server_address[1]
            uploads = [
                {
                    "estimator": page["estimator"],
                    "page_number": page["page_number"],
                    "files": {
                        name: f"http://127.0.0.1:{port}/store/{page['estimator']}/{page['page_number']}/{name}"
                        for name in page["files"]
                    },
                }
                for page in payload["pages"]
            ]
            return self.answer(200, {"uploads": uploads, "revision": REVISION})
        missing = [
            {"estimator": estimator["name"], "page_number": page["page_number"]}
            for estimator in payload["estimators"]
            for page in estimator["pages"]
            if any(
                FakeServer.storage.get(f"{estimator['name']}/{page['page_number']}/{name}")
                != (entry["size"], entry["md5"])
                for name, entry in page["files"].items()
            )
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
    FakeServer.dropped_once, FakeServer.expired_once, FakeServer.errors, FakeServer.payloads = set(), set(), [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    write_convertmc(tmp_path)
    monkeypatch.setattr(results_uploader, "RETRY_SECONDS", 0)
    yield SimpleNamespace(
        output_dir=str(tmp_path), sim_id=1, update_key="key", backend_url=f"http://127.0.0.1:{server.server_address[1]}"
    )
    server.shutdown()


def objects() -> int:
    """Objects of the test results' pages: zarr.json, and the shard of a page with values"""
    return sum(2 if page["data"]["values"] else 1 for estimator in RESULTS for page in estimator["pages"])


def test_uploader_uploads_every_page_and_reports_done(fake_server):
    """convertmc's JSON (a cluster without a Python that has pymchelper) arrives as pages in ZARR_FORMAT, every
    object of them, then the job is done under the revision the backend named
    """
    assert results_uploader.main(fake_server) == 0

    assert len(FakeServer.storage) == objects()
    assert FakeServer.calls == ["/results/uploads", "/results/done"]
    assert FakeServer.payloads[-1]["revision"] == REVISION and "partial" not in FakeServer.payloads[-1]
    pages_dir = Path(fake_server.output_dir) / "pages"
    first = RESULTS[0]
    page_dir = pages_dir / first["name"] / str(first["pages"][0]["metadata"]["page_number"])
    files = {path.relative_to(page_dir).as_posix(): path.read_bytes() for path in page_dir.rglob("*") if path.is_file()}
    page = result_format.json_page(*result_format.read_page(files))
    assert page["data"].pop("values") == pytest.approx(first["pages"][0]["data"]["values"], rel=1e-6)
    expected = json.loads(json.dumps(first["pages"][0]))
    expected["data"].pop("values")
    assert page == expected


def test_uploader_uploads_what_the_merger_wrote(fake_server, tmp_path):
    """The manifest results_merger.py writes is uploaded as it is, partial results with their primaries"""
    output_dir = tmp_path / "merged"
    output_dir.mkdir()
    results_merger.main(["--output_dir", str(output_dir), str(BDO_DIR / "task_*" / "*.bdo")])
    fake_server.output_dir, fake_server.partial = str(output_dir), True

    assert results_uploader.main(fake_server) == 0

    manifest = json.loads((output_dir / "results.json").read_text())
    assert FakeServer.payloads[-1]["partial"] is True and FakeServer.payloads[-1]["primaries"] == 400
    assert FakeServer.payloads[-1]["estimators"] == manifest["estimators"]
    assert len(FakeServer.storage) == sum(len(page["files"]) for e in manifest["estimators"] for page in e["pages"])


def test_uploader_ends_partial_results_the_backend_no_longer_takes(fake_server):
    """409: the simulation stopped running, the final results come next; no failure"""
    FakeServer.errors = [409]
    fake_server.partial = True

    assert results_uploader.main(fake_server) == 0
    assert FakeServer.calls == ["/results/uploads"]


def test_uploader_uploads_missing_pages_again(fake_server):
    """A page the storage lost is uploaded again, only that one"""
    first = RESULTS[0]
    FakeServer.lost_once = {f"{first['name']}/{first['pages'][0]['metadata']['page_number']}/zarr.json"}

    assert results_uploader.main(fake_server) == 0

    assert FakeServer.calls == ["/results/uploads", "/results/done", "/results/uploads", "/results/done"]


def test_uploader_sends_the_old_way_without_storage(fake_server):
    """A backend without object storage gets the results in one request"""
    FakeServer.has_storage = False

    assert results_uploader.main(fake_server) == 0

    assert FakeServer.calls == ["/results/uploads", "/results"]
    sent = FakeServer.payloads[-1]["estimators"]
    expected = {estimator["name"]: estimator for estimator in RESULTS}
    assert sorted(estimator["name"] for estimator in sent) == sorted(expected)
    for estimator in sent:
        values = estimator["pages"][0]["data"]["values"]
        assert values == pytest.approx(expected[estimator["name"]]["pages"][0]["data"]["values"], rel=1e-6)


def first_page_key() -> str:
    """The fake storage's key of the first page's metadata"""
    return f"{RESULTS[0]['name']}/{RESULTS[0]['pages'][0]['metadata']['page_number']}/zarr.json"


def test_uploader_survives_a_dropped_connection(fake_server):
    """A connection broken during an upload is retried, not the end of the simulation"""
    FakeServer.dropped_once = {first_page_key()}

    assert results_uploader.main(fake_server) == 0

    assert len(FakeServer.storage) == objects()


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
