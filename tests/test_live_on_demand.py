"""Live and on-demand partial results: result files read page by page, saves and merges spaced by the size of the
results, locks a killed merge cannot hold for long, and partial results removed a while after the simulation ended
"""

import filecmp
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from pymchelper.input_output import fromfile

from yaptide.application import create_app
from yaptide.batch import bdo_pages, merge_groups, result_format
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    CelerySimulationModel,
    EstimatorModel,
    ExpiringObjectModel,
    YaptideUserModel,
)
from yaptide.routes import common_sim_routes
from yaptide.routes.common_sim_routes import clean_partial_results, store_partial_results, store_results
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.utils import sim_utils

BDO_FILES = sorted((Path(__file__).parent / "res" / "bdo").rglob("*.bdo"))
RESULTS = json.loads((Path(__file__).parent / "res" / "json_with_results.json").read_text())["estimators"]


@pytest.mark.parametrize("path", BDO_FILES, ids=lambda path: path.name)
def test_a_copy_with_every_page_is_the_file_itself(tmp_path: Path, path: Path):
    """Nothing is lost or reordered: copying all pages gives the same bytes"""
    assert bdo_pages.copy_pages(path, tmp_path / path.name, lambda info: True) == len(fromfile(str(path)).pages)
    assert filecmp.cmp(path, tmp_path / path.name, shallow=False)


@pytest.mark.parametrize("path", BDO_FILES, ids=lambda path: path.name)
def test_pages_left_out_are_not_in_the_copy(tmp_path: Path, path: Path):
    """The pages kept read as pymchelper reads them from the whole file, numbers and values alike"""
    whole = fromfile(str(path))
    assert [info.dimensions for info in bdo_pages.pages_of(path)] == [page.dimension for page in whole.pages]
    bdo_pages.copy_pages(path, tmp_path / path.name, lambda info: info.dimensions <= 1)
    lines = [page for page in whole.pages if page.dimension <= 1]
    copied = fromfile(str(tmp_path / path.name)).pages
    assert len(copied) == len(lines)
    for page, line in zip(copied, lines):
        assert page.page_number == line.page_number and np.array_equal(page.data_raw, line.data_raw)


def test_a_file_cut_short_within_a_page_is_refused(tmp_path: Path):
    """The simulator still writes it: the copy would miss a page"""
    path = BDO_FILES[0]
    short = tmp_path / path.name
    short.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(bdo_pages.BdoError):
        bdo_pages.pages_of(short)
    with pytest.raises(bdo_pages.BdoError):
        bdo_pages.copy_pages(short, tmp_path / "copy.bdo", lambda info: True)
    short.write_bytes(b"not a result file at all")
    with pytest.raises(bdo_pages.BdoError):
        bdo_pages.pages_of(short)


@pytest.mark.parametrize(
    "dimensions, mcpl, mode",
    [
        (0, False, result_format.LIVE),
        (1, False, result_format.LIVE),
        (2, False, result_format.ON_DEMAND),
        (3, False, result_format.FINAL_ONLY),
        (0, True, result_format.FINAL_ONLY),
    ],
)
def test_pages_by_dimensions(dimensions, mcpl, mode):
    """Points and lines live, maps on demand, volumes and particle lists only in the final results"""
    assert result_format.partial_mode(dimensions, mcpl) == mode


def test_live_merges_are_spaced_by_the_size_of_a_save():
    """15 s at least, longer for large saves, at most 10 minutes"""
    assert result_format.live_interval(0) == result_format.LIVE_MIN_SECONDS == 15
    assert result_format.live_interval(400e6) == pytest.approx(60)
    assert result_format.live_interval(1e12) == result_format.LIVE_MAX_SECONDS


MESH = """Geometry Mesh
    Name Volume
    X -1 1 {x}
    Y -1 1 {y}
    Z 0 10 {z}

Output
    Filename volume.bdo
    Geo Volume
    Quantity Dose
    Quantity Fluence Protons
"""


def test_result_size_is_estimated_from_the_detectors():
    """Bins of every output's mesh, times its quantities, 8 bytes each; nothing to size gives None"""
    assert sim_utils.estimated_result_bytes(MESH.format(x=10, y=20, z=30)) == 10 * 20 * 30 * 2 * 8
    assert sim_utils.estimated_result_bytes("") is None


@pytest.mark.parametrize(
    "bins, saves",
    [((1, 1, 2000), sim_utils.MAX_SAVES), ((400, 400, 300), 2), ((2000, 600, 100), sim_utils.MIN_SAVES)],
)
def test_large_results_are_saved_less_often(bins, saves):
    """SHIELD-HIT12A writes every page at each save: a 2 GB budget of saves for each task"""
    files = {"beam.dat": "NSTAT 100000 0\n", "detect.dat": MESH.format(x=bins[0], y=bins[1], z=bins[2])}
    sim_utils.set_shieldhit_save_step(files, 100000)
    assert files["beam.dat"].startswith(f"NSTAT 100000    {100000 // (saves + 1)}\n")


def test_a_lock_is_kept_alive_by_its_merge(tmp_path: Path, monkeypatch):
    """A merge holding a lock touches it, so it is not taken over however long the merge takes"""
    monkeypatch.setattr(merge_groups, "HEARTBEAT_SECONDS", 0.05)
    lock = tmp_path / "partial.lock.0"
    assert merge_groups.take_lock(lock)
    merge_groups.own_lock(lock)
    old = time.time() - merge_groups.LOCK_SECONDS - 1
    os.utime(lock, (old, old))
    os.utime(lock / merge_groups.OWNER_FILE, (old, old))
    time.sleep(0.3)
    assert merge_groups.lock_alive(lock) and not merge_groups.take_lock(lock)
    merge_groups.free_lock(lock)
    assert not lock.exists()


def test_a_lock_of_a_killed_merge_is_taken_over_soon(tmp_path: Path):
    """A merge killed (out of memory, its task's time limit) no longer touches its lock: another takes it over after
    LOCK_SECONDS, a minute and a half, not an hour
    """
    assert merge_groups.LOCK_SECONDS <= 120
    lock = tmp_path / "partial.lock.final"
    assert merge_groups.take_lock(lock)
    (lock / merge_groups.OWNER_FILE).write_text("12345")
    assert not merge_groups.take_lock(lock)
    old = time.time() - merge_groups.LOCK_SECONDS - 1
    os.utime(lock, (old, old))
    os.utime(lock / merge_groups.OWNER_FILE, (old, old))
    assert not merge_groups.lock_alive(lock)
    assert merge_groups.take_lock(lock)
    assert not (lock / merge_groups.OWNER_FILE).exists()
    assert not list(tmp_path.glob(".*stale*"))


def test_the_collect_does_not_wait_for_a_killed_group_merge(tmp_path: Path):
    """A group's final merge that was killed leaves its lock: the collect merges the group's files at once"""
    merge_groups.plan(tmp_path, 4, 3 << 30)  # two groups of two
    for task in range(1, 5):
        directory = merge_groups.task_dir(tmp_path, task)
        directory.mkdir(parents=True)
        (directory / "dose.bdo").write_bytes(b"")
    lock = tmp_path / merge_groups.GROUPS_DIR / "0" / f"{merge_groups.FINAL_DIR}.lock"
    lock.mkdir(parents=True)
    old = time.time() - merge_groups.LOCK_SECONDS - 1
    os.utime(lock, (old, old))
    started = time.monotonic()
    files = merge_groups.final_files(tmp_path, 4, wait_seconds=60)
    assert time.monotonic() - started < 5 and len(files) == 4


@pytest.fixture
def app_context(tmp_path, monkeypatch):
    """A database with one running simulation; removals of stored pages noted instead"""
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'yaptide.db'}")
    removed = []
    monkeypatch.setattr(common_sim_routes.result_storage, "delete_pages", removed.extend)
    app = create_app()
    with app.app_context():
        db.create_all()
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
        simulation = CelerySimulationModel(
            job_id="partialjob",
            user_id=user.id,
            input_type=InputType.FILES.value,
            sim_type=SimulationType.SHIELDHIT.value,
            title="partial",
            job_state=EntityState.RUNNING.value,
        )
        db.session.add(simulation)
        db.session.commit()
        yield simulation.id, removed
        db.session.remove()
        db.drop_all()


def test_partial_pages_replaced_by_the_final_ones_go_15_minutes_later(app_context):
    """A browser may still load the partial results it was shown: their pages stay a while after the end"""
    simulation_id, removed = app_context
    simulation = db.session.get(CelerySimulationModel, simulation_id)
    assert store_partial_results(simulation, RESULTS, 300)
    common_sim_routes.expire_pages(simulation_id, ["simulations/1/a/0/r1", "simulations/1/b/0/r1"])
    store_results(simulation, RESULTS)
    assert removed == []

    clean_partial_results(datetime.now(timezone.utc) + timedelta(minutes=14))
    assert removed == [] and db.session.query(ExpiringObjectModel).count() == 2
    clean_partial_results(datetime.now(timezone.utc) + timedelta(minutes=16))
    assert removed == ["simulations/1/a/0/r1", "simulations/1/b/0/r1"]
    assert db.session.query(ExpiringObjectModel).count() == 0


@pytest.mark.parametrize("state", [EntityState.FAILED.value, EntityState.CANCELED.value])
def test_partial_results_of_a_simulation_that_did_not_complete_go_15_minutes_after_its_end(app_context, state):
    """Without final results the partial ones stay a while for the user, then go"""
    simulation_id, _ = app_context
    simulation = db.session.get(CelerySimulationModel, simulation_id)
    assert store_partial_results(simulation, RESULTS, 300)
    simulation.job_state = state
    simulation.end_time = datetime.now(timezone.utc)
    db.session.commit()

    clean_partial_results(datetime.now(timezone.utc) + timedelta(minutes=10))
    assert db.session.query(EstimatorModel).count() == len(RESULTS)
    clean_partial_results(datetime.now(timezone.utc) + timedelta(minutes=16))
    assert db.session.query(EstimatorModel).count() == 0
    assert db.session.get(CelerySimulationModel, simulation_id).partial_primaries is None
