"""Large SHIELD-HIT12A meshes: the merge one task file at a time, pages downsampled for the UI with the full
resolution kept for download
"""

import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pymchelper.input_output import fromfile
from pymchelper.writers.json import JsonWriter

from yaptide.application import create_app
from yaptide.batch import merge_results
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, YaptideUserModel
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.utils.sim_utils import merge_simulation_outputs

BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
# a mesh of 1 x 4 x 10 bins, 3 pages (dose and two fluences)
TEMPLATE = BDO_DIR / "task_1" / "yz_profile_0001.bdo"


def make_bdo(path: Path, bins: tuple, primaries: int, seed: int) -> None:
    """A task's .bdo file like TEMPLATE, with another mesh, primaries and random values in every page"""
    rng = np.random.default_rng(seed)
    with open(TEMPLATE, "rb") as source, open(path, "wb") as target:
        target.write(source.read(24))
        while header := source.read(24):
            tag, kind, count = struct.unpack("<Q8sQ", header)
            dtype = np.dtype(kind.rstrip(b"\0").decode())
            payload = source.read(count * dtype.itemsize)
            if tag == 0xE004:
                payload = np.array(bins, dtype=dtype).tobytes()
            elif tag == merge_results.BDO_NSTAT:
                payload = np.array([primaries], dtype=dtype).tobytes()
            elif tag == merge_results.BDO_DATA:
                header = struct.pack("<Q8sQ", tag, kind, int(np.prod(bins)))
                payload = rng.random(int(np.prod(bins))).astype(dtype).tobytes()
            target.write(header + payload)


@pytest.fixture
def task_dirs(tmp_path) -> list[Path]:
    """Three tasks with a mesh of 7 x 1 x 9 bins, run with 100, 200 and 300 primaries"""
    dirs = []
    for task in range(1, 4):
        task_dir = tmp_path / f"task_{task}"
        task_dir.mkdir()
        make_bdo(task_dir / f"mesh_{task:04d}.bdo", (7, 1, 9), task * 100, task)
        dirs.append(task_dir)
    return dirs


def test_estimators_have_pymchelpers_json_format(tmp_path):
    """Pages shown in full come in the JSON pymchelper writes, values merged as before (one task: the file itself)"""
    for file in sorted((BDO_DIR / "task_1").glob("*.bdo")):
        estimator = merge_results.merge_estimator_files([str(file)])
        JsonWriter(str(tmp_path / "expected"), None).write(estimator)

        assert merge_results.estimator_dict(estimator) == json.loads((tmp_path / "expected.json").read_text())


def test_streaming_merge_weights_tasks_by_primaries(task_dirs):
    """The merge one file at a time gives the mean of all tasks weighted by their primaries"""
    files = [str(next(task_dir.glob("*.bdo"))) for task_dir in task_dirs]
    merged = merge_results.merge_estimator_files(files)

    estimators = [fromfile(file) for file in files]
    for number, page in enumerate(merged.pages):
        expected = sum(e.pages[number].data_raw * e.number_of_primaries for e in estimators) / 600
        np.testing.assert_allclose(page.data_raw, expected, rtol=1e-12)
    assert merged.number_of_primaries == 600


def test_block_factors_bring_the_bins_down():
    """The axis with the most bins shown is reduced first, one bin stays one"""
    assert merge_results.block_factors((10000, 1, 10000, 1, 1), 1_000_000) == [10, 1, 10, 1, 1]
    assert merge_results.block_factors((7, 1, 9, 1, 1), 20) == [2, 1, 2, 1, 1]
    assert merge_results.block_factors((5, 1, 1, 1, 1), 5) == [1, 1, 1, 1, 1]


def test_block_mean_averages_partial_blocks_over_their_bins():
    """A last block shorter than the others averages the bins it has"""
    data = np.arange(7 * 3, dtype=float).reshape(7, 3)

    reduced = merge_results.block_mean(data, [3, 2])

    assert reduced.shape == (3, 2)
    assert reduced[0, 0] == data[0:3, 0:2].mean()
    assert reduced[2, 0] == data[6:7, 0:2].mean()
    assert reduced[2, 1] == data[6, 2]


def test_large_pages_are_downsampled_and_kept_in_full(task_dirs, tmp_path, monkeypatch):
    """A page over DISPLAY_MAX_BINS is shown as block means at the blocks' centres; the full resolution is a .bdo
    file pymchelper reads as the merged estimator
    """
    monkeypatch.setattr(merge_results, "DISPLAY_MAX_BINS", 20)
    full_dir = tmp_path / "full"
    full_dir.mkdir()

    (estimator,) = merge_simulation_outputs(task_dirs, full_dir)

    files = [str(next(task_dir.glob("*.bdo"))) for task_dir in task_dirs]
    merged = merge_results.merge_estimator_files(files)
    for page, merged_page in zip(estimator["pages"], merged.pages, strict=True):
        assert page["metadata"]["downsampled"] == {"bins": [7, 1, 9], "shown": [4, 1, 5]}
        values = np.array(page["data"]["values"]).reshape((4, 5), order="F")
        grid = merged_page.data_raw.reshape((7, 9), order="F")
        assert len(page["data"]["values"]) == 20
        np.testing.assert_allclose(values[0, 0], grid[0:2, 0:2].mean(), rtol=1e-12)
        np.testing.assert_allclose(values[3, 4], grid[6, 8], rtol=1e-12)
        x, z = merged.x.data, merged.z.data
        np.testing.assert_allclose(page["axis_dim1"]["values"], [x[0:2].mean(), x[2:4].mean(), x[4:6].mean(), x[6]])
        np.testing.assert_allclose(
            page["axis_dim2"]["values"], [z[0:2].mean(), z[2:4].mean(), z[4:6].mean(), z[6:8].mean(), z[8]]
        )

    full = fromfile(str(full_dir / f"{estimator['name']}.bdo"))
    assert full.number_of_primaries == 600
    for page, merged_page in zip(full.pages, merged.pages, strict=True):
        np.testing.assert_allclose(page.data_raw, merged_page.data_raw, rtol=1e-12)


def test_small_pages_are_not_downsampled(task_dirs, tmp_path):
    """Nothing to download apart from what the UI shows"""
    (estimator,) = merge_simulation_outputs(task_dirs, tmp_path)

    assert not any("downsampled" in page["metadata"] for page in estimator["pages"])
    assert not list(tmp_path.glob("*.bdo"))


def test_merge_script_writes_the_files_of_the_collect_job(task_dirs, tmp_path, monkeypatch):
    """The script the HPC jobs run: a JSON file per estimator, the full resolution next to it; nothing to merge
    fails
    """
    output = tmp_path / "output"
    output.mkdir()
    script = Path(merge_results.__file__)
    run = [sys.executable, str(script), f"--output_dir={output}"]

    assert subprocess.run([*run, str(tmp_path / "task_*" / "*.bdo")], check=False).returncode == 0
    assert json.loads((output / "mesh.json").read_text())["pages"][0]["metadata"]["page_number"] == "0"
    assert subprocess.run([*run, str(tmp_path / "none_*" / "*.bdo")], check=False).returncode == 1


@pytest.fixture
def client(monkeypatch):
    """Test client of a logged in user, its direct simulation with results stored, and the storage's links"""
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "put_page", lambda key, page: 123)
    monkeypatch.setattr(result_storage, "page_url", lambda key: f"https://storage.test/{key}?signature")
    app = create_app()
    with app.app_context():
        db.create_all()
        user = YaptideUserModel(username="Gandalf")
        user.set_password("Mellon")
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        client.set_cookie("access_token", encode_auth_token(user.id)[0], domain="127.0.0.1")
        yield client
        db.session.remove()
        db.drop_all()


def test_results_link_the_full_resolution(client, task_dirs, monkeypatch):
    """An estimator with its full resolution stored has a signed link to it, with all estimators and with pages"""
    monkeypatch.setattr(merge_results, "DISPLAY_MAX_BINS", 20)
    simulation = CelerySimulationModel(
        job_id="large",
        user_id=db.session.query(YaptideUserModel.id).scalar(),
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="large",
        job_state=EntityState.RUNNING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    (estimator,) = merge_simulation_outputs(task_dirs)
    key = result_storage.full_resolution_key(simulation.id, estimator["name"])
    estimator["full_resolution"] = {"key": key, "size": 1000}
    payload = {"simulation_id": simulation.id, "update_key": encode_simulation_auth_token(simulation.id)}
    assert client.post("/results", json={**payload, "estimators": [estimator]}).status_code == 202

    url = f"https://storage.test/{key}?signature"
    everything = client.get("/results", query_string={"job_id": "large"}).get_json()
    assert everything["estimators"][0]["full_resolution_url"] == url
    assert "full_resolution" not in everything["estimators"][0]["metadata"]
    query = {"job_id": "large", "estimator_name": estimator["name"]}
    assert client.get("/results", query_string=query).get_json()["full_resolution_url"] == url
    assert (
        client.get("/results", query_string={**query, "page_numbers": "0-2"}).get_json()["full_resolution_url"] == url
    )
    assert client.get("/results", query_string={**query, "page_number": 0}).get_json()["full_resolution_url"] == url
    assert key == f"simulations/{simulation.id}/mesh/mesh.bdo"
