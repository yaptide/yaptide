"""Partial results carry pages by their dimensions: points and lines always, maps when the user asks for them, volumes
only in the final results (yaptide/batch/result_format.py)
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yaptide.application import create_app
from yaptide.batch import merge_groups, result_format, results_merger
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import BatchSimulationModel, ClusterModel, KeycloakUserModel, SimulationModel
from yaptide.routes import common_sim_routes
from yaptide.routes.utils.tokens import encode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType

BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
FILES = [str(path) for task in ("task_1", "task_2") for path in sorted((BDO_DIR / task).glob("*.bdo"))]
# the test results: entrance and peak hold points and a line, z_profile lines, yz_profile maps only
MAPS_ONLY = "yz_profile"


@pytest.mark.parametrize(
    "dimensions, mode",
    [(0, result_format.LIVE), (1, result_format.LIVE), (2, result_format.ON_DEMAND), (3, result_format.FINAL_ONLY)],
)
def test_mode_by_dimensions(dimensions, mode):
    """Points and lines are live, maps on demand, volumes only final"""
    assert result_format.partial_mode(dimensions) == mode


def test_partial_results_leave_out_maps_unless_asked_for(tmp_path: Path):
    """Without a request the maps are not merged; an estimator of maps only is left out, the others keep the numbers
    of their pages
    """
    manifest = results_merger.write_directory(FILES, tmp_path / "live", modes=result_format.partial_modes(False))
    full = results_merger.write_directory(FILES, tmp_path / "full")

    names = [estimator["name"] for estimator in manifest["estimators"]]
    assert MAPS_ONLY not in names and MAPS_ONLY in [estimator["name"] for estimator in full["estimators"]]
    for estimator in manifest["estimators"]:
        whole = next(other for other in full["estimators"] if other["name"] == estimator["name"])
        live = [page for page in whole["pages"] if page["dimensions"] <= result_format.LIVE_DIMENSIONS]
        assert estimator["pages"] == live  # the same numbers and the same values
    assert manifest["primaries"] == full["primaries"]

    asked = results_merger.write_directory(FILES, tmp_path / "asked", modes=result_format.partial_modes(True))
    assert asked["estimators"] == full["estimators"]


def test_final_only_pages_are_never_merged_for_partial_results(tmp_path: Path, monkeypatch):
    """A page above the on-demand dimensions is left out of partial results, even when the user asks"""
    monkeypatch.setattr(result_format, "ON_DEMAND_DIMENSIONS", 1)
    manifest = results_merger.write_directory(FILES, tmp_path, modes=result_format.partial_modes(True))
    assert MAPS_ONLY not in [estimator["name"] for estimator in manifest["estimators"]]


def test_group_merges_carry_the_live_pages_only(tmp_path: Path):
    """A group's partial merge reads the points and lines only: the maps are merged apart, when asked for"""
    target = tmp_path / "group"
    merge_groups.write_merged(FILES, target, merge_groups.GROUP_PARTIAL_MODES)
    merged = merge_groups.merged_files(target)
    assert merged and not any(Path(file).name.startswith(MAPS_ONLY) for file in merged)


def test_partial_merges_read_only_their_pages(tmp_path: Path, monkeypatch):
    """A live merge never reads the values of a map, an on-demand merge never those of a line (bdo_pages)"""
    read = []
    copy = results_merger.bdo_pages.copy_pages

    def copy_pages(source, target, keep):
        """Notes which pages were copied out to be read"""
        kept = copy(source, target, keep)
        read.extend(page.dimensions for page in results_merger.bdo_pages.pages_of(target))
        return kept

    monkeypatch.setattr(results_merger.bdo_pages, "copy_pages", copy_pages)
    results_merger.write_directory(FILES, tmp_path / "live", modes=result_format.kind_modes(result_format.LIVE))
    assert read and max(read) <= result_format.LIVE_DIMENSIONS
    read.clear()
    manifest = results_merger.write_directory(
        FILES, tmp_path / "maps", modes=result_format.kind_modes(result_format.ON_DEMAND)
    )
    assert set(read) == {2} and [estimator["name"] for estimator in manifest["estimators"]] == [MAPS_ONLY]


class FakeResponse:
    """What urlopen gives, as a context manager"""

    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_job_looks_for_the_request_with_its_signed_link(tmp_path: Path, monkeypatch):
    """The last partial merge asks storage for the on-demand object; no link (a job submitted before) means no"""
    assert not merge_groups.on_demand_requested(tmp_path)

    (tmp_path / merge_groups.LINKS_FILE).write_text(json.dumps({"on_demand": "https://storage.test/od?signed"}))
    asked = []
    monkeypatch.setattr(
        merge_groups.request, "urlopen", lambda req, **kwargs: asked.append(req.get_method()) or FakeResponse(200)
    )
    assert merge_groups.on_demand_requested(tmp_path) and asked == ["HEAD"]

    def missing(req, **kwargs):
        raise merge_groups.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(merge_groups.request, "urlopen", missing)
    assert not merge_groups.on_demand_requested(tmp_path)


@pytest.mark.parametrize("kind", [result_format.LIVE, result_format.ON_DEMAND])
def test_each_kind_of_partial_merge_takes_its_pages(tmp_path: Path, monkeypatch, kind: str):
    """The live merge uploads the points and lines, the on-demand merge the maps of the latest saves of all tasks"""
    merged = {}

    def write_directory(files, output, modes=None):
        """Notes what was merged"""
        merged.update(modes=modes, files=files)
        return {"estimators": [], "primaries": 0}

    monkeypatch.setattr(results_merger, "write_directory", write_directory)
    save = tmp_path / "workspaces" / "task_0001" / "saves" / "100"
    save.mkdir(parents=True)
    (save / "dose.bdo").write_bytes(Path(FILES[0]).read_bytes())
    merge_groups.plan(tmp_path, 1, 10)
    args = SimpleNamespace(
        root=str(tmp_path), ntasks=1, group=0, kind=kind, sim_id=1, update_key="key", backend_url="https://b.test"
    )
    assert merge_groups.partial(args) == 0  # nothing to upload: not a failure
    assert merged["modes"] == result_format.kind_modes(kind) and merged["files"] == [str(save / "dose.bdo")]
    assert not list(tmp_path.glob("partial.lock.*"))


@pytest.fixture
def client(monkeypatch):
    """Test client signed in as the owner of a running HPC simulation, with object storage kept in a set"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    objects = set()
    monkeypatch.setattr(
        result_storage, "put_on_demand", lambda sim_id: objects.add(result_storage.on_demand_key(sim_id))
    )
    monkeypatch.setattr(
        result_storage, "on_demand_requested", lambda sim_id: result_storage.on_demand_key(sim_id) in objects
    )
    monkeypatch.setattr(
        result_storage, "clear_on_demand", lambda sim_id: objects.discard(result_storage.on_demand_key(sim_id))
    )
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
            job_state=EntityState.RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        test_client = app.test_client()
        test_client.set_cookie("access_token", encode_auth_token(user.id, is_keycloak=True)[0], domain="127.0.0.1")
        test_client.objects = objects
        test_client.simulation_id = simulation.id
        yield test_client
        db.session.remove()
        db.drop_all()


def test_the_user_asks_for_the_on_demand_pages(client, monkeypatch):
    """A request is stored for the jobs to find, and reported until partial results carry the maps"""
    # the pages themselves are stored as test_results_upload.py checks
    monkeypatch.setattr(common_sim_routes, "prepare_estimators_and_pages", lambda *args: None)
    assert client.get("/results/on_demand?job_id=hpcjob").get_json()["requested"] is False
    assert client.post("/results/on_demand", json={"job_id": "hpcjob"}).status_code == 202
    assert client.get("/results/on_demand?job_id=hpcjob").get_json()["requested"] is True

    line = {"name": "z", "metadata": {}, "pages": [{"metadata": {"page_number": 0}, "dimensions": 1, "data": {}}]}
    simulation = db.session.get(BatchSimulationModel, client.simulation_id)
    common_sim_routes.store_partial_results(simulation, [line], 100)
    assert client.get("/results/on_demand?job_id=hpcjob").get_json()["requested"] is True

    a_map = {"name": "yz", "metadata": {}, "pages": [{"metadata": {"page_number": 0}, "dimensions": 2, "data": {}}]}
    common_sim_routes.store_partial_results(simulation, [line, a_map], 200)
    assert client.get("/results/on_demand?job_id=hpcjob").get_json()["requested"] is False


def test_only_a_running_simulation_of_the_user_takes_a_request(client, monkeypatch):
    """Another user's or an unknown job is refused, as is a simulation no longer running or a server without storage"""
    assert client.post("/results/on_demand", json={"job_id": "nosuchjob"}).status_code != 202
    assert client.post("/results/on_demand", json={}).status_code == 400

    db.session.query(SimulationModel).update({"job_state": EntityState.MERGING_RUNNING.value})
    db.session.commit()
    assert client.post("/results/on_demand", json={"job_id": "hpcjob"}).status_code == 409

    db.session.query(SimulationModel).update({"job_state": EntityState.RUNNING.value})
    db.session.commit()
    monkeypatch.delenv("RESULTS_S3_BUCKET")
    assert client.post("/results/on_demand", json={"job_id": "hpcjob"}).status_code == 501
    assert not client.objects
