"""Large SHIELD-HIT12A meshes: the merge one task file at a time, pages downsampled for the UI with the full
resolution kept for download, the size limit at submit and the memory the HPC jobs ask for
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
from yaptide.batch import merge_results, simulation_data_sender
from yaptide.batch.batch_methods import with_merge_memory
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, LogfilesModel, SimulationModel, YaptideUserModel
from yaptide.routes.common_sim_routes import store_results
from yaptide.routes.utils.tokens import encode_auth_token, encode_simulation_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType
from yaptide.utils.sim_utils import (
    detect_outputs,
    merge_memory_error,
    merge_memory_gb,
    merge_simulation_outputs,
    output_size_error,
)

BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
# a mesh of 1 x 4 x 10 bins, 3 pages (dose and two fluences)
TEMPLATE = BDO_DIR / "task_1" / "yz_profile_0001.bdo"

# the detect.dat of simulation 2089, whose merge ran out of memory on Ares
DETECT_2089 = """Geometry Mesh
    Name XZ_map
    X -5 5 10000
    Y -0.5 0.5 1
    Z 0 10 10000

Geometry Mesh
    Name XY_map
    X -3 3 300
    Y -3 3 300
    Z 4 5 1

Geometry Mesh
    Name Z_narrow
    X -0.1 0.1 1
    Y -0.1 0.1 1
    Z 0 20 200

Output
    Filename XZ_map.bdo
    Geo XZ_map
    Quantity Dose

Output
    Filename XY_map.bdo
    Geo XY_map
    Quantity Dose

Output
    Filename z_profile.bdo
    Geo Z_narrow
    Quantity Dose
    Quantity Fluence
    Quantity AvgEnergy
    Quantity dLET

Output
    Filename z_more.bdo
    Geo Z_narrow
    Quantity Dose
    Quantity Fluence
    Quantity AvgEnergy
    Quantity dLET
    Quantity tLET
"""


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

    assert b"mesh.bdo" in (full_dir / "mesh.bdo").read_bytes()  # its own name, not the first task's
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


def test_size_of_simulation_2089():
    """XZ_map 10000 x 1 x 10000 with one quantity takes 800 MB a task: 100 tasks are over the limit, 50 are not"""
    outputs = {output.name: output for output in detect_outputs(DETECT_2089)}

    assert outputs["XZ_map"].bins == [10000, 1, 10000] and outputs["XZ_map"].values == 10**8
    assert outputs["XY_map"].values == 300 * 300
    assert outputs["z_profile"].values == 200 * 4 and outputs["z_more"].values == 200 * 5
    assert output_size_error({"detect.dat": DETECT_2089}, 100) == (
        "The outputs would take 80 GB (XZ_map: 10000 × 1 × 10000 bins × 100 tasks); the limit is 50 GB. "
        "Use fewer bins or tasks."
    )
    assert output_size_error({"detect.dat": DETECT_2089}, 50) is None
    assert output_size_error({"input.inp": "FLUKA"}, 1000) is None


def test_cylinders_and_differential_bins_count():
    """Cyl: R x PHI x Z; a Diff1/Diff2 multiplies the bins of the quantity before it; a Zone is one bin"""
    detect = """Geometry Cyl
    Name Cyl
    R 0 5 10
    PHI 0 360 4
    Z 0 20 100
Geometry Zone
    Name Slab
    Zone 1 3
Output
    Filename cyl.bdo
    Geo Cyl
    Quantity Dose
    Quantity Fluence Protons
    Diff1 0 160 640
    Diff1Type E
Output
    Geo Slab
    Quantity Dose ! a comment
"""
    cyl, slab = detect_outputs(detect)

    assert (cyl.name, cyl.bins, cyl.values, cyl.pages) == ("cyl", [10, 4, 100], 4000 * 641, 2)
    assert (slab.name, slab.bins, slab.values) == ("Slab", [1], 1)


def test_names_with_spaces_and_rounding_as_the_ui():
    """The whole Filename names the output; GB are rounded half up (52.5 GB: 53)"""
    detect = "Geometry Mesh\n Name M\n X 0 1 25000\n Y 0 1 1\n Z 0 1 2625\n"
    detect += "Output\n Filename Profile XZ.bdo\n Geo M\n Quantity Dose\n"  # 52.5 GB in 100 tasks

    assert output_size_error({"detect.dat": detect}, 100) == (
        "The outputs would take 53 GB (Profile XZ: 25000 × 1 × 2625 bins × 100 tasks); the limit is 50 GB. "
        "Use fewer bins or tasks."
    )


def test_unreadable_numbers_leave_the_output_out():
    """A typo in a number of bins is SHIELD-HIT12A's to report: that output is not estimated, nothing fails"""
    detect = "Geometry Mesh\n Name A\n X -5 5 1O\nGeometry Mesh\n Name B\n X -5 5 inf\nGeometry Mesh\n Name C\n"
    detect += " X 0 1 10\nOutput\n Geo A\n Quantity Dose\nOutput\n Geo B\n Quantity Dose\n"
    detect += "Output\n Geo C\n Quantity Dose\n Diff1 0 1 nan\nOutput\n Geo C\n Quantity Dose\n"

    assert [(output.name, output.values) for output in detect_outputs(detect)] == [("C", 10)]


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


def test_submit_over_the_limit_is_refused(client):
    """400 with the reason, nothing stored"""
    payload = {
        "input_type": "files",
        "sim_type": "shieldhit",
        "ntasks": 100,
        "input_files": {"beam.dat": "NSTAT 10000 0\n", "geo.dat": "", "mat.dat": "", "detect.dat": DETECT_2089},
    }

    response = client.post("/jobs/direct", json=payload)

    assert response.status_code == 400
    assert response.get_json()["message"].startswith("The outputs would take 80 GB (XZ_map")
    assert db.session.query(CelerySimulationModel).count() == 0
    assert client.post("/jobs/direct", json={**payload, "ntasks": 50}).status_code == 202


def test_submit_with_an_unreadable_detect_dat_is_taken(client):
    """No estimate for what cannot be read, the simulation is stored as before"""
    detect = "Geometry Mesh\n Name A\n X -5 5 1O\nOutput\n Geo A\n Quantity Dose\n"
    files = {"beam.dat": "NSTAT 10 0\n", "geo.dat": "", "mat.dat": "", "detect.dat": detect}
    payload = {"input_type": "files", "sim_type": "shieldhit", "ntasks": 1, "input_files": files}

    assert client.post("/jobs/direct", json=payload).status_code == 202
    assert db.session.query(CelerySimulationModel).count() == 1


def large_simulation(client, task_dirs, monkeypatch, forged: bool = False) -> tuple[int, dict]:
    """A direct simulation with a downsampled estimator; forged: its job claims a full resolution in the results"""
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
    if forged:
        claim = {"key": "simulations/999/secret/0.json", "size": 1}
        estimator = {
            **estimator,
            "full_resolution": claim,
            "metadata": {**estimator["metadata"], "full_resolution": claim},
        }
    return simulation.id, estimator


def test_results_tell_of_the_full_resolution(client, task_dirs, monkeypatch):
    """An estimator the server stored the full resolution of says so, with all estimators and with pages"""
    sim_id, estimator = large_simulation(client, task_dirs, monkeypatch)
    store_results(db.session.get(SimulationModel, sim_id), [estimator], frozenset({estimator["name"]}))

    everything = client.get("/results", query_string={"job_id": "large"}).get_json()
    assert everything["estimators"][0]["full_resolution"] is True
    assert "full_resolution" not in everything["estimators"][0]["metadata"]
    query = {"job_id": "large", "estimator_name": estimator["name"]}
    for extra in ({}, {"page_numbers": "0-2"}, {"page_number": 0}):
        assert client.get("/results", query_string={**query, **extra}).get_json()["full_resolution"] is True


def test_full_resolution_download_redirects_to_a_signed_link(client, task_dirs, monkeypatch):
    """The owner is sent to a fresh signed link of the estimator's own object; no file, or another user: none"""
    sim_id, estimator = large_simulation(client, task_dirs, monkeypatch)
    store_results(db.session.get(SimulationModel, sim_id), [estimator], frozenset({estimator["name"]}))
    query = {"job_id": "large", "estimator_name": estimator["name"]}

    response = client.get("/results/full_resolution", query_string=query)

    assert response.status_code == 302
    assert response.headers["Location"] == f"https://storage.test/simulations/{sim_id}/mesh/mesh.bdo?signature"
    assert client.get("/results/full_resolution", query_string={**query, "estimator_name": "mesh_"}).status_code == 404
    other = YaptideUserModel(username="Saruman")
    other.set_password("Orthanc")
    db.session.add(other)
    db.session.commit()
    client.set_cookie("access_token", encode_auth_token(other.id)[0], domain="127.0.0.1")
    assert client.get("/results/full_resolution", query_string=query).status_code == 403


def test_a_job_cannot_claim_a_full_resolution(client, task_dirs, monkeypatch):
    """A full resolution in the results a job sends (in the metadata or beside it) is ignored: no link to any key"""
    sim_id, estimator = large_simulation(client, task_dirs, monkeypatch, forged=True)
    payload = {"simulation_id": sim_id, "update_key": encode_simulation_auth_token(sim_id)}
    assert client.post("/results", json={**payload, "estimators": [estimator]}).status_code == 202

    content = client.get("/results", query_string={"job_id": "large"}).get_json()["estimators"][0]
    assert "full_resolution" not in content and "full_resolution" not in content["metadata"]
    query = {"job_id": "large", "estimator_name": estimator["name"]}
    assert client.get("/results/full_resolution", query_string=query).status_code == 404


def test_hpc_jobs_ask_for_the_memory_of_the_merge():
    """3 copies of the largest output, its pages' JSON and a base; never below the cluster's default for the job's
    CPUs, nor in place of the user's own memory options
    """
    files = {"detect.dat": DETECT_2089}
    assert merge_memory_gb(files) == 5  # 3 * 800 MB + 64 MiB + 2 GiB, rounded up

    options = with_merge_memory({"array_options": {"account": "grant"}}, files)
    assert options["array_options"] == {"account": "grant", "mem": "5G"}
    assert options["collect_options"] == {"mem": "5G"}

    own = with_merge_memory({"array_header": "#SBATCH --mem-per-cpu=8G", "collect_options": {"mem": "9G"}}, files)
    assert "array_options" not in own and own["collect_options"] == {"mem": "9G"}
    bind = with_merge_memory({"array_header": "#SBATCH --mem-bind=local"}, files)
    assert bind["array_options"] == {"mem": "5G"}

    # 2 CPUs get 7700 MB anyway: more than the 5 GB the merge takes
    cpus = with_merge_memory({"array_options": {"cpus-per-task": "2"}, "collect_header": "#SBATCH -c 2"}, files)
    assert cpus == {"array_options": {"cpus-per-task": "2"}, "collect_header": "#SBATCH -c 2"}

    small = {"array_options": {"account": "grant"}}
    assert with_merge_memory(small, {"detect.dat": DETECT_2089.replace("10000", "100")}) == small


def test_merges_larger_than_a_node_are_refused():
    """More memory than a node has: refused at submit, never asked of SLURM"""
    huge = {"detect.dat": DETECT_2089.replace("Z 0 10 10000", "Z 0 10 900000")}  # 9e9 bins

    assert merge_memory_error({"detect.dat": DETECT_2089}) is None
    assert merge_memory_error(huge) == (
        "Merging the results would need 204 GB of memory, more than a node of the cluster has (180 GB). Use fewer bins."
    )
    # a simulation stored before the check never asks for more than a node has
    assert with_merge_memory({}, huge)["array_options"] == {"mem": "180G"}


@pytest.mark.parametrize(
    "state, reason", [("OUT_OF_MEMORY", "out_of_memory"), ("FAILED", None), ("TIMEOUT", None), ("", None)]
)
def test_reporter_tells_a_merge_out_of_memory(monkeypatch, state, reason):
    """The reporter job reads the collect job's state from SLURM's accounting"""
    calls = []

    def sacct(command, **_):
        """sacct's answer"""
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=state + "\n")

    monkeypatch.setattr(simulation_data_sender.subprocess, "run", sacct)
    monkeypatch.setattr(simulation_data_sender, "SACCT_RETRY_SECONDS", 0)

    assert simulation_data_sender.collect_failure_reason("123") == reason
    assert calls[0] == ["sacct", "-n", "-P", "-X", "-j", "123", "-o", "State"]


class Accepted:
    """The backend's answer to a state report"""

    def __enter__(self):
        """The answer itself"""
        return self

    def __exit__(self, *_):
        """Nothing to close"""

    @staticmethod
    def getcode() -> int:
        """Accepted"""
        return 202


def test_failure_reason_goes_with_the_failed_state(monkeypatch):
    """The reason is a log the backend stores with the FAILED state (POST /jobs)"""
    sent = []
    monkeypatch.setattr(
        simulation_data_sender.request, "urlopen", lambda req, **_: sent.append(json.loads(req.data)) or Accepted()
    )

    simulation_data_sender.send_simulation_state_update(1, "key", "https://backend", "FAILED", "out_of_memory")

    assert sent == [
        {
            "sim_id": 1,
            "job_state": "FAILED",
            "update_key": "key",
            "log": {"error": "Merging the results ran out of memory"},
        }
    ]


def test_a_failure_keeps_its_first_reason(client):
    """The collect job and the reporter job may both report the out of memory: one log"""
    simulation = CelerySimulationModel(
        job_id="oom",
        user_id=db.session.query(YaptideUserModel.id).scalar(),
        input_type=InputType.FILES.value,
        sim_type=SimulationType.SHIELDHIT.value,
        title="oom",
        job_state=EntityState.MERGING_RUNNING.value,
    )
    db.session.add(simulation)
    db.session.commit()
    report = {"sim_id": simulation.id, "update_key": encode_simulation_auth_token(simulation.id), "job_state": "FAILED"}
    log = {"error": simulation_data_sender.REASONS["out_of_memory"]}

    for _ in range(2):
        assert client.post("/jobs", json={**report, "log": log}).status_code == 202

    assert db.session.query(LogfilesModel).filter_by(simulation_id=simulation.id).count() == 1
