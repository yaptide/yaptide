"""Partial results carry pages by their dimensions: points and lines while someone looks, a map when the user asks for
that page, volumes only in the final results (yaptide/batch/result_format.py); and the routes the browser tells the
backend through what it looks at
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from yaptide.application import create_app
from yaptide.batch import merge_groups, result_format, results_merger
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    BatchSimulationModel,
    ClusterModel,
    KeycloakUserModel,
    PartialPageModel,
    PartialViewerModel,
    SimulationModel,
)
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
    """A live merge never reads the values of a map, a merge of a page asked for only that page's (bdo_pages): what
    pymchelper reads holds no other page
    """
    read = []
    read_bdo = results_merger.read_bdo

    def noting(file):
        """Notes the pages of each file pymchelper reads"""
        read.extend((Path(file).name, info.number, info.dimensions) for info in results_merger.bdo_pages.pages_of(file))
        return read_bdo(file)

    monkeypatch.setattr(results_merger, "read_bdo", noting)
    results_merger.write_directory(FILES, tmp_path / "live", modes=result_format.kind_modes(result_format.LIVE))
    assert read and max(dimensions for _, _, dimensions in read) <= result_format.LIVE_DIMENSIONS
    read.clear()
    manifest = results_merger.write_directory(FILES, tmp_path / "page", pages={MAPS_ONLY: {1}})
    assert {(number, dimensions) for _, number, dimensions in read} == {(1, 2)}
    assert [(e["name"], [p["page_number"] for p in e["pages"]]) for e in manifest["estimators"]] == [(MAPS_ONLY, [1])]


def test_a_file_holding_only_the_pages_wanted_is_read_as_it_is(tmp_path: Path, monkeypatch):
    """No copy when every page of a file is wanted (a save holds only the pages of partial results), and pymchelper's
    reader of the format is called directly: no guess of the format, which reads the whole file more than once
    """
    monkeypatch.setattr(results_merger, "fromfile", lambda file: pytest.fail("the format was guessed"))
    monkeypatch.setattr(
        results_merger.bdo_pages, "copy_file", lambda *args: pytest.fail("a file of wanted pages only was copied")
    )
    estimator = results_merger.read_estimator(str(BDO_DIR / "task_1" / "yz_profile_0001.bdo"), modes={result_format.ON_DEMAND})
    assert [page.dimension for page in estimator.pages] == [2, 2, 2]


def test_live_partial_results_announce_the_maps(tmp_path: Path):
    """The live pages come with stubs of the maps (number, name and dimensions, no values), an estimator of maps only
    with its stubs alone, so the user can ask for one before any was merged
    """
    stubs = results_merger.page_stubs(FILES, {result_format.ON_DEMAND})
    manifest = results_merger.write_directory(FILES, tmp_path, modes={result_format.LIVE}, stubs=stubs)
    maps = next(estimator for estimator in manifest["estimators"] if estimator["name"] == MAPS_ONLY)
    assert maps["pages"] == [
        {"page_number": number, "name": name, "dimensions": 2, "stub": True}
        for number, name in enumerate(["DOSE", "FLUENCE", "FLUENCE"])
    ]
    assert not list((tmp_path / MAPS_ONLY).glob("*"))


@pytest.mark.parametrize("kind", [result_format.LIVE, result_format.ON_DEMAND])
def test_each_kind_of_partial_merge_takes_its_pages(tmp_path: Path, monkeypatch, kind: str):
    """The live merge uploads the points and lines (with stubs of the maps), the merge of pages asked for those
    pages of the latest saves of all tasks
    """
    merged = {}

    def write_directory(files, output, modes=None, pages=None, stubs=None):
        """Notes what was merged"""
        merged.update(modes=modes, files=files, pages=pages, stubs=stubs)
        return {"estimators": [], "primaries": 0}

    monkeypatch.setattr(results_merger, "write_directory", write_directory)
    save = tmp_path / "workspaces" / "task_0001" / "saves" / "100"
    save.mkdir(parents=True)
    (save / "yz_profile.bdo").write_bytes(Path(FILES[2]).read_bytes())
    merge_groups.plan(tmp_path, 1, 10)
    args = SimpleNamespace(
        root=str(tmp_path),
        ntasks=1,
        group=0,
        kind=kind,
        sim_id=1,
        update_key="key",
        backend_url="https://b.test",
        pages=result_format.pages_argument([("yz_profile", 1)]),
    )
    assert merge_groups.partial(args) == 0  # nothing to upload: not a failure
    assert merged["files"] == [str(save / "yz_profile.bdo")]
    if kind == result_format.LIVE:
        assert merged["modes"] == {result_format.LIVE} and merged["pages"] is None and "yz_profile" in merged["stubs"]
    else:
        assert merged["modes"] is None and merged["pages"] == {"yz_profile": {1}} and merged["stubs"] is None
        assert (tmp_path / f"{merge_groups.PARTIAL_STAMP}.{merge_groups.ON_DEMAND_LOCK}").exists()
    assert not list(tmp_path.glob("partial.lock.*"))


def test_live_results_of_the_same_saves_are_not_uploaded_again(tmp_path: Path, monkeypatch):
    """No one's save changed since the last live partial results: no merge, no upload"""
    merges = []
    monkeypatch.setattr(
        results_merger,
        "write_directory",
        lambda files, output, **kwargs: merges.append(files) or {"estimators": [{"name": "d", "pages": []}], "primaries": 1},
    )
    monkeypatch.setattr(merge_groups.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    save = tmp_path / "workspaces" / "task_0001" / "saves" / "100"
    save.mkdir(parents=True)
    (save / "dose.bdo").write_bytes(Path(FILES[0]).read_bytes())
    args = SimpleNamespace(ntasks=1, sim_id=1, update_key="key", backend_url="https://b.test")
    units = merge_groups.latest_saves(tmp_path, 1)
    assert merge_groups.merge_and_upload(tmp_path, units, args) == 0
    assert merge_groups.merge_and_upload(tmp_path, units, args) == 0
    assert len(merges) == 1
    newer = save.parent / "200"
    save.rename(newer)
    assert merge_groups.merge_and_upload(tmp_path, merge_groups.latest_saves(tmp_path, 1), args) == 0
    assert len(merges) == 2


@pytest.fixture
def client(monkeypatch):
    """Test client signed in as the owner of a running HPC simulation, the wanted objects in storage kept in a dict"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    objects = {}
    monkeypatch.setattr(result_storage, "put_wanted", lambda sim_id, body: objects.__setitem__(sim_id, json.loads(body)))
    monkeypatch.setattr(result_storage, "delete_wanted", lambda sim_id: objects.pop(sim_id, None))
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


def beat(client, closed=False, viewer="tab1", job_ids=("hpcjob",)):
    """A beat of a browser tab with the app open"""
    return client.post("/results/watch", json={"job_ids": list(job_ids), "viewer": viewer, "closed": closed})


LINE = {"name": "z", "metadata": {}, "pages": [{"metadata": {"page_number": 0}, "dimensions": 1, "data": {}}]}
MAP_STUBS = {
    "name": "yz",
    "metadata": {},
    "pages": [
        {"page_number": 0, "name": "DOSE", "dimensions": 2, "stub": True},
        {"page_number": 1, "name": "FLUENCE", "dimensions": 2, "stub": True},
    ],
}


def test_live_pages_are_wanted_while_a_tab_beats(client, monkeypatch):
    """A beat makes the live pages wanted for WANTED_LIVE_SECONDS; a tab that closes ends it unless another beats"""
    assert beat(client).status_code == 200
    live_until = client.objects[client.simulation_id]["live_until"]
    assert abs(live_until - time.time() - result_format.WANTED_LIVE_SECONDS) < 5
    assert beat(client, viewer="tab2").get_json()["simulations"]["hpcjob"]["live"] is True

    beat(client, closed=True)
    assert client.objects[client.simulation_id]["live_until"] > time.time()  # tab2 still beats
    beat(client, closed=True, viewer="tab2")
    assert client.objects[client.simulation_id]["live_until"] == 0

    # a tab that stopped beating counts as gone after WANTED_LIVE_SECONDS
    beat(client)
    db.session.query(PartialViewerModel).update(
        {"last_seen": datetime.now(timezone.utc) - timedelta(seconds=result_format.WANTED_LIVE_SECONDS + 1)}
    )
    db.session.commit()
    assert common_sim_routes.wanted_state(client.simulation_id)[0] == 0


def test_a_map_is_asked_for_alone_and_kept_with_its_time(client, monkeypatch):
    """The live partial results announce the maps; one asked for is listed in the wanted object until partial results
    carry it, then shows when it was merged and of how many primaries
    """
    monkeypatch.setattr(common_sim_routes, "prepare_estimators_and_pages", lambda *args: None)
    simulation = db.session.get(BatchSimulationModel, client.simulation_id)
    assert client.post("/results/on_demand", json={"job_id": "hpcjob", "file": "yz", "page_number": 1}).status_code == 404

    common_sim_routes.store_partial_results(simulation, [LINE, MAP_STUBS], 100)
    pages = client.get("/results/on_demand?job_id=hpcjob").get_json()["pages"]
    assert [(page["file"], page["page_number"], page["name"], page["merged_at"]) for page in pages] == [
        ("yz", 0, "DOSE", None),
        ("yz", 1, "FLUENCE", None),
    ]
    assert simulation.partial_primaries == 100

    assert client.post("/results/on_demand", json={"job_id": "hpcjob", "file": "yz", "page_number": 1}).status_code == 202
    assert client.objects[client.simulation_id]["pages"] == [{"estimator": "yz", "page": 1}]

    # live partial results again: the request stays
    common_sim_routes.store_partial_results(simulation, [LINE, MAP_STUBS], 200)
    assert client.objects[client.simulation_id]["pages"] == [{"estimator": "yz", "page": 1}]

    a_map = {"name": "yz", "metadata": {}, "pages": [{"metadata": {"page_number": 1, "name": "FLUENCE"}, "dimensions": 2}]}
    common_sim_routes.store_partial_results(simulation, [a_map], 300)
    assert client.objects[client.simulation_id]["pages"] == []
    page = client.get("/results/on_demand?job_id=hpcjob").get_json()["pages"][1]
    assert page["requested_at"] is None and page["merged_at"] and page["primaries"] == 300


def test_only_a_running_simulation_of_the_user_takes_a_request(client):
    """Another user's or an unknown job is refused, as is a simulation no longer running; a beat skips them"""
    simulation = db.session.get(BatchSimulationModel, client.simulation_id)
    common_sim_routes.store_partial_results(simulation, [MAP_STUBS], 100)
    request = {"job_id": "hpcjob", "file": "yz", "page_number": 0}
    assert client.post("/results/on_demand", json=dict(request, job_id="nosuchjob")).status_code != 202
    assert client.post("/results/on_demand", json={"job_id": "hpcjob"}).status_code == 400
    assert client.post("/results/watch", json={"job_ids": ["hpcjob"], "viewer": "no spaces"}).status_code == 400
    assert beat(client, job_ids=["nosuchjob"]).get_json()["simulations"] == {}

    db.session.query(SimulationModel).update({"job_state": EntityState.MERGING_RUNNING.value})
    db.session.commit()
    assert client.post("/results/on_demand", json=request).status_code == 409


def test_final_results_forget_who_looked_and_what_was_asked(client, monkeypatch):
    """The wanted object goes with the final results, and so do the viewers and the maps noted"""
    monkeypatch.setattr(common_sim_routes, "prepare_estimators_and_pages", lambda *args: None)
    simulation = db.session.get(BatchSimulationModel, client.simulation_id)
    beat(client)
    common_sim_routes.store_partial_results(simulation, [LINE, MAP_STUBS], 100)
    common_sim_routes.store_results(simulation, [LINE])
    assert client.simulation_id not in client.objects
    assert db.session.query(PartialViewerModel).count() == 0 and db.session.query(PartialPageModel).count() == 0
