"""Merging an HPC simulation's results in groups of tasks on the cluster: partial results and the collect"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from yaptide.batch import merge_groups, result_format, results_merger

BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
N_TASKS = 4


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    """A simulation's directory with four tasks' result files (the two of the test data, twice) and small groups:
    two of two tasks
    """
    monkeypatch.setattr(merge_groups, "GROUP_BYTES", 1)
    for task in range(1, N_TASKS + 1):
        source = BDO_DIR / f"task_{(task - 1) % 2 + 1}"
        target = merge_groups.task_dir(tmp_path, task)
        target.mkdir(parents=True)
        for path in source.glob("*.bdo"):
            shutil.copyfile(path, target / path.name.replace(path.name[-9:-4], f"{task:04d}"))
    (tmp_path / "done").mkdir()
    return tmp_path


def pages(output: Path) -> dict:
    """The merged pages in an output directory: (estimator, page number) -> (page without values, values)"""
    manifest = json.loads((output / results_merger.MANIFEST).read_text())
    result = {}
    for estimator in manifest["estimators"]:
        for page in estimator["pages"]:
            page_dir = output / estimator["name"] / str(page["page_number"])
            objects = {name: (page_dir / name).read_bytes() for name in page["files"]}
            result[estimator["name"], page["page_number"]] = result_format.read_page(objects)
    return result


def assert_same_pages(output: Path, expected: Path) -> None:
    """The pages hold the same metadata and values (float32: a second merge rounds differently in the last digit)"""
    merged, direct = pages(output), pages(expected)
    assert merged.keys() == direct.keys()
    for key, (page, values) in merged.items():
        assert page == direct[key][0]
        np.testing.assert_allclose(values, direct[key][1], rtol=1e-6)


def all_files(root: Path) -> list:
    """Every task's result files"""
    return sorted(str(path) for path in root.glob("workspaces/task_*/*.bdo"))


@pytest.mark.parametrize(
    "task_bytes, n_tasks, size",
    [
        (100 << 20, 10, 10),  # 1 GB in all: one merge
        (100 << 20, 200, 20),  # 20 GB: groups of 2 GB
        (1 << 30, 400, 20),  # a task 1 GB: groups of the square root of the tasks, not of two
        (10 << 30, 2, 2),  # two tasks are one group, however large
    ],
)
def test_group_size(task_bytes, n_tasks, size):
    """Groups of GROUP_BYTES of result files, at least the square root of the tasks"""
    assert merge_groups.group_size(task_bytes, n_tasks) == size


def test_the_first_plan_wins(tmp_path: Path):
    """Every task and the collect use the group size planned first, whatever size they saw"""
    assert merge_groups.plan(tmp_path, 400, 1 << 30) == 20
    assert merge_groups.plan(tmp_path, 400, 1) == 20
    assert merge_groups.read_plan(tmp_path) == 20
    assert [merge_groups.group_of(task, 20, 400) for task in (1, 20, 21, 400)] == [0, 0, 1, 19]
    assert list(merge_groups.group_tasks(19, 20, 390)) == list(range(381, 391))


def test_the_last_task_of_a_group_merges_it_and_the_collect_merges_the_groups(root: Path, tmp_path_factory):
    """Each group merged once by its last task to end; the collect's pages are the ones of merging every task's files
    at once, the counts of files and primaries included
    """
    for task in (1, 3, 2):
        (root / "done" / f"task_{task}").touch()
        assert merge_groups.main(["task_end", f"--root={root}", f"--ntasks={N_TASKS}", f"--task={task}"]) == 0
    assert merge_groups.read_plan(root) == 2
    assert (root / "groups" / "0" / "final").is_dir()
    assert not (root / "groups" / "1" / "final").exists()  # task 4 still runs
    (root / "done" / "task_4").touch()
    merge_groups.main(["task_end", f"--root={root}", f"--ntasks={N_TASKS}", "--task=4"])
    assert len(merge_groups.merged_files(root / "groups" / "1" / "final")) == len(list(BDO_DIR.glob("task_1/*.bdo")))

    output = root / "output"
    assert merge_groups.main(["collect", f"--root={root}", f"--ntasks={N_TASKS}", f"--output_dir={output}"]) == 0

    expected = tmp_path_factory.mktemp("direct")
    direct = results_merger.write_directory(all_files(root), expected)
    manifest = json.loads((output / results_merger.MANIFEST).read_text())
    assert manifest["primaries"] == direct["primaries"] == 800
    assert [e["metadata"] for e in manifest["estimators"]] == [e["metadata"] for e in direct["estimators"]]
    assert all(e["metadata"]["file_counter"] == str(N_TASKS) for e in manifest["estimators"])
    assert_same_pages(output, expected)


def test_the_collect_merges_the_files_of_a_group_without_its_merge(root: Path, tmp_path_factory):
    """A group whose merge failed (or whose last task was killed) is merged from its tasks' files"""
    for task in (1, 2):
        (root / "done" / f"task_{task}").touch()
        merge_groups.main(["task_end", f"--root={root}", f"--ntasks={N_TASKS}", f"--task={task}"])
    # group 1's merge left its lock behind, long ago
    (root / "groups" / "1").mkdir(parents=True)
    (root / "groups" / "1" / "final.lock").mkdir()

    files = merge_groups.final_files(root, N_TASKS, wait_seconds=0)

    assert sum(file.endswith(".pkl") for file in files) == len(list(BDO_DIR.glob("task_1/*.bdo")))
    assert sum("task_0003" in file or "task_0004" in file for file in files) == 2 * len(list(BDO_DIR.glob("task_1/*")))
    output, expected = root / "output", tmp_path_factory.mktemp("direct")
    results_merger.write_directory(files, output)
    results_merger.write_directory(all_files(root), expected)
    assert_same_pages(output, expected)


def test_small_results_are_one_merge(tmp_path: Path):
    """Results within GROUP_BYTES: no groups, the collect merges the tasks' files"""
    for task in (1, 2):
        shutil.copytree(BDO_DIR / f"task_{task}", merge_groups.task_dir(tmp_path, task))
        (tmp_path / "done").mkdir(exist_ok=True)
        (tmp_path / "done" / f"task_{task}").touch()
        merge_groups.main(["task_end", f"--root={tmp_path}", "--ntasks=2", f"--task={task}"])
    assert not (tmp_path / "groups").exists()
    assert merge_groups.final_files(tmp_path, 2) == all_files(tmp_path)


def save(root: Path, task: int, primaries: int) -> None:
    """A save of the task kept by its watcher: its result files under saves/<primaries>/"""
    task_path = merge_groups.task_dir(root, task)
    shutil.copytree(task_path, task_path / "saves" / str(primaries), ignore=shutil.ignore_patterns("saves"))


@pytest.fixture
def uploads(monkeypatch) -> list:
    """The partial results the uploader got: the manifests"""
    uploaded = []

    def run(command, check):
        """The uploader, reading what it would upload"""
        output = Path(next(arg for arg in command if arg.startswith("--output_dir=")).split("=", 1)[1])
        assert "--partial" in command
        uploaded.append(json.loads((output / results_merger.MANIFEST).read_text()))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(merge_groups.subprocess, "run", run)
    return uploaded


def partial(root: Path, group: int) -> int:
    """The partial script's merge, for a group whose lock the watcher took"""
    merge_groups.lock_path(root, group).mkdir()
    args = ["partial", f"--root={root}", f"--ntasks={N_TASKS}", f"--group={group}"]
    return merge_groups.main(args + ["--sim_id=1", "--update_key=key", "--backend_url=https://yaptide.test"])


def test_partial_results_merge_the_group_then_the_groups(root: Path, uploads: list, monkeypatch):
    """A group's latest saves are merged into a file per estimator, named by their primaries; the last merge takes
    those of every group, or a group's saves while it has none, and uploads them. The locks are freed
    """
    merge_groups.plan(root, N_TASKS, 1)
    for task in range(1, N_TASKS + 1):
        save(root, task, 100)
    save(root, 1, 300)

    assert partial(root, 0) == 0

    assert [path.name for path in merge_groups.numbered_dirs(root / "groups" / "0")] == ["400"]
    assert not (root / "groups" / "1").exists()
    (manifest,) = uploads
    # group 0's merge (tasks' primaries as the files hold them) and group 1's saves
    assert manifest["primaries"] == 800
    assert not list(root.glob("partial.lock.*"))
    assert not (root / merge_groups.PARTIAL_OUTPUT).exists()

    # the last merge waits PARTIAL_SECONDS; the group's merge does not
    save(root, 4, 400)
    assert partial(root, 1) == 0
    assert len(uploads) == 1 and (root / "groups" / "1" / "500").is_dir()
    monkeypatch.setattr(merge_groups, "PARTIAL_SECONDS", 0)
    save(root, 3, 300)
    assert partial(root, 1) == 0
    assert len(uploads) == 2
    # the older merges but the latest two go
    assert [path.name for path in merge_groups.numbered_dirs(root / "groups" / "1")] == ["500", "700"]


def test_partial_results_of_one_group_are_one_merge(tmp_path: Path, uploads: list):
    """Small results: the latest saves of all tasks merged and uploaded at once, no merges of groups kept"""
    for task in (1, 2):
        shutil.copytree(BDO_DIR / f"task_{task}", merge_groups.task_dir(tmp_path, task) / "saves" / "100")
    merge_groups.plan(tmp_path, 2, 1)
    merge_groups.lock_path(tmp_path, 0).mkdir()

    args = ["partial", f"--root={tmp_path}", "--ntasks=2", "--group=0", "--sim_id=1", "--update_key=k"]
    assert merge_groups.main(args + ["--backend_url=https://yaptide.test"]) == 0

    assert len(uploads) == 1 and uploads[0]["primaries"] == 400
    assert not (tmp_path / "groups").exists() and not merge_groups.lock_path(tmp_path, 0).exists()


def test_a_stopped_merge_frees_only_its_locks(tmp_path: Path):
    """The watcher frees the locks its stopped merge held (or had not marked yet), not another merge's"""
    mine, theirs, unmarked = (merge_groups.lock_path(tmp_path, name) for name in (0, "final", 1))
    for lock in (mine, theirs, unmarked):
        lock.mkdir()
    (mine / merge_groups.OWNER_FILE).write_text("123")
    (theirs / merge_groups.OWNER_FILE).write_text("456")

    merge_groups.free_locks(tmp_path, 123, 0)
    merge_groups.free_locks(tmp_path, 123, 1)

    assert not mine.exists() and theirs.exists() and not unmarked.exists()


def test_planning_needs_the_standard_library_only():
    """The watcher imports this module with the cluster's plain Python"""
    script = Path(merge_groups.__file__)
    code = f"import sys; sys.path.insert(0, {str(script.parent)!r}); import merge_groups; merge_groups.group_size(1, 2)"
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
