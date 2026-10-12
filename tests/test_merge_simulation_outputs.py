"""Merging of direct simulation results straight from the simulator's output files"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from pymchelper.run import main as convertmc

from yaptide.direct import simulation
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
    """Copies of the task directories, as run_simulation leaves them for finish_simulation"""
    return [Path(shutil.copytree(task_dir, tmp_path / task_dir.name)) for task_dir in TASK_DIRS]


def test_finish_simulation_merges_and_removes_directories(task_outputs: list[Path], monkeypatch):
    """finish_simulation merges the successful tasks, sends the failed task's logfiles and removes the directories"""
    sent_logfiles = {}

    def fake_send_logfiles(logfiles: dict, **_) -> bool:
        """Records the logfiles instead of sending them to the backend"""
        sent_logfiles.update(logfiles)
        return True

    monkeypatch.setattr(simulation, "send_simulation_logfiles", fake_send_logfiles)
    results = [
        {"output_dir": str(task_outputs[0])},
        {"logfiles": {"shieldhit_0003.log": "crashed"}},
        {"output_dir": str(task_outputs[1])},
    ]

    final_result = simulation.finish_simulation(results, simulation_id=None, update_key=None)

    # without an update key the results cannot be sent, so they are returned
    assert [estimator["name"] for estimator in final_result["estimators"]] == ESTIMATOR_NAMES
    assert sent_logfiles == {"shieldhit_0003.log": "crashed"}
    assert not task_outputs[0].exists()
    assert not task_outputs[1].exists()


def test_failed_task_removes_its_work_dir(tmp_path: Path):
    """A task that raises leaves no working directory behind"""
    work_dir = tmp_path / f"{simulation.WORK_DIR_PREFIX}1_0"

    with pytest.raises(ValueError):
        simulation.run_simulation({"beam.dat": ""}, 0, "unknown", work_dir, simulation_id=1, report=print)

    assert not work_dir.exists()


@pytest.fixture
def backend_posts(monkeypatch) -> list:
    """Records what finish_simulation would send to the backend"""
    posts = []

    def fake_send_job_state(simulation_id: int, update_key: str, update_dict: dict, **_) -> bool:
        """Records a job state update"""
        posts.append(("jobs", update_dict["job_state"]))
        return True

    def fake_send(**kwargs) -> bool:
        """Records sent results or logfiles"""
        posts.append(("results" if "estimators" in kwargs else "logfiles", None))
        return True

    monkeypatch.setattr(simulation, "send_job_state", fake_send_job_state)
    monkeypatch.setattr(simulation, "send_simulation_results", fake_send)
    monkeypatch.setattr(simulation, "send_simulation_logfiles", fake_send)
    return posts


def test_finish_simulation_fails_when_task_results_are_missing(task_outputs: list[Path], backend_posts: list):
    """A missing working directory (e.g. after a Ray restart) marks the simulation failed, not partially merged"""
    shutil.rmtree(task_outputs[1])
    results = [{"output_dir": str(path)} for path in task_outputs]

    simulation.finish_simulation(results, simulation_id=1, update_key="key")

    assert backend_posts == [("jobs", "MERGING_RUNNING"), ("jobs", "FAILED")]
    assert not task_outputs[0].exists()


def test_finish_simulation_fails_when_all_tasks_failed(backend_posts: list):
    """When every task failed the logfiles are sent and the simulation is marked failed"""
    results = [{"logfiles": {"shieldhit_0001.log": "crashed"}}]

    simulation.finish_simulation(results, simulation_id=1, update_key="key")

    assert backend_posts == [("jobs", "MERGING_RUNNING"), ("logfiles", None), ("jobs", "FAILED")]


def test_finish_simulation_sends_nothing_after_cancel(task_outputs: list[Path], backend_posts: list):
    """A simulation cancelled while merging stores no results, but its directories are still removed"""
    results = [{"output_dir": str(path)} for path in task_outputs]

    simulation.finish_simulation(results, simulation_id=1, update_key="key", cancelled=lambda: True)

    assert backend_posts == [("jobs", "MERGING_RUNNING")]
    assert not any(path.exists() for path in task_outputs)
