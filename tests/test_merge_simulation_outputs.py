"""Merging of direct simulation results straight from the simulator's output files"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from pymchelper.run import main as convertmc

from yaptide.celery import tasks
from yaptide.utils.sim_utils import merge_simulation_outputs

# two SHIELD-HIT12A tasks of the test input with tiny meshes, run with 100 and 300 primaries
BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
TASK_DIRS = [BDO_DIR / "task_1", BDO_DIR / "task_2"]
ESTIMATOR_NAMES = ["entrance", "peak", "yz_profile", "z_profile"]


def test_merge_matches_convertmc(tmp_path: Path):
    """Direct merge gives the same values as convertmc, which merges batch simulations"""
    assert convertmc(["json", "--many", str(BDO_DIR / "task_*" / "*.bdo"), str(tmp_path)]) == 0

    merged = merge_simulation_outputs(TASK_DIRS)

    assert [estimator["name"] for estimator in merged] == ESTIMATOR_NAMES
    for estimator in merged:
        expected = json.loads((tmp_path / f"{estimator['name']}.json").read_text())
        assert {key: value for key, value in estimator.items() if key != "name"} == expected


def test_merge_weights_tasks_by_primaries():
    """A task with more primaries counts more, a plain mean of the two tasks would differ"""
    merged = {estimator["name"]: estimator for estimator in merge_simulation_outputs(TASK_DIRS)}
    single = [
        {estimator["name"]: estimator for estimator in merge_simulation_outputs([task_dir])} for task_dir in TASK_DIRS
    ]

    dose = np.array(merged["z_profile"]["pages"][0]["data"]["values"])
    dose_100, dose_300 = (np.array(task["z_profile"]["pages"][0]["data"]["values"]) for task in single)

    np.testing.assert_allclose(dose, (100 * dose_100 + 300 * dose_300) / 400, rtol=1e-9)
    assert not np.allclose(dose, (dose_100 + dose_300) / 2)


def test_merge_sorts_estimators_by_name(tmp_path: Path):
    """Estimators come sorted by name even when the first task lacks one of them"""
    first_task = Path(shutil.copytree(TASK_DIRS[0], tmp_path / "task_1"))
    (first_task / "entrance_0001.bdo").unlink()

    merged = merge_simulation_outputs([first_task, TASK_DIRS[1]])

    assert [estimator["name"] for estimator in merged] == ESTIMATOR_NAMES


def test_merge_without_output_files(tmp_path: Path):
    """Directories without result files give no estimators"""
    assert not merge_simulation_outputs([tmp_path])
    assert not merge_simulation_outputs([])


@pytest.fixture
def task_outputs(tmp_path: Path) -> list[Path]:
    """Copies of the task directories, as run_single_simulation leaves them for merge_results"""
    return [Path(shutil.copytree(task_dir, tmp_path / task_dir.name)) for task_dir in TASK_DIRS]


def test_merge_results_task_merges_and_removes_directories(task_outputs: list[Path], monkeypatch):
    """merge_results merges the successful tasks, keeps the failed task's logfiles and removes the directories"""
    sent_logfiles = {}

    def fake_send_logfiles(logfiles: dict, **_) -> bool:
        """Records the logfiles instead of sending them to the backend"""
        sent_logfiles.update(logfiles)
        return True

    monkeypatch.setattr(tasks, "send_simulation_logfiles", fake_send_logfiles)
    results = [
        {"output_dir": str(task_outputs[0]), "keep_output_dir": False, "simulation_id": None, "update_key": None},
        {"logfiles": {"shieldhit_0003.log": "crashed"}, "simulation_id": None, "update_key": None},
        {"output_dir": str(task_outputs[1]), "keep_output_dir": True, "simulation_id": None, "update_key": None},
    ]

    final_result = tasks.merge_results(results)

    # without an update key the results cannot be sent, so they are returned
    assert [estimator["name"] for estimator in final_result["estimators"]] == ESTIMATOR_NAMES
    assert sent_logfiles == {"shieldhit_0003.log": "crashed"}
    assert not task_outputs[0].exists()
    assert task_outputs[1].exists()


def test_failed_task_removes_its_work_dir(tmp_path: Path, monkeypatch):
    """A task that raises leaves no working directory behind"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMP", raising=False)

    # an unknown simulator type raises after the working directory was created
    with pytest.raises(NameError):
        tasks.run_single_simulation.run(files_dict={"beam.dat": ""}, task_id=1, sim_type="unknown")

    assert not list(tmp_path.glob(f"{tasks.WORK_DIR_PREFIX}*"))


def test_worker_start_removes_stale_work_dirs(tmp_path: Path, monkeypatch):
    """Working directories left by jobs that never merged are removed when the worker starts"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMP", raising=False)
    stale = tmp_path / f"{tasks.WORK_DIR_PREFIX}abc"
    stale.mkdir()
    other = tmp_path / "other"
    other.mkdir()

    tasks.remove_stale_work_dirs()

    assert not stale.exists()
    assert other.exists()
