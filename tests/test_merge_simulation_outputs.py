"""Merging of direct simulation results straight from the simulator's output files"""

import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from pymchelper.run import main as convertmc

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
        assert estimator["metadata"] == expected["metadata"]
        for page, expected_page in zip(estimator["pages"], expected["pages"], strict=True):
            values, expected_values = page["data"].pop("values"), expected_page["data"].pop("values")
            np.testing.assert_allclose(values, expected_values, rtol=1e-12)  # summation order differs from convertmc
            assert page == expected_page


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
