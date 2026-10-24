"""Merging result files into pages in ZARR_FORMAT, on the backend and on the clusters, one estimator at a time"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from yaptide.batch import result_format, results_merger, results_uploader
from yaptide.batch.shieldhit_string_templates import FIND_MERGE_PYTHON, PARTIAL_SHIELDHIT_BASH
from yaptide.utils.sim_utils import merge_simulation_outputs

BDO_DIR = Path(__file__).resolve().parent / "res" / "bdo"
TASK_DIRS = [BDO_DIR / "task_1", BDO_DIR / "task_2"]


def page_files(page_dir: Path) -> dict:
    """The objects of a page written into a directory: name -> bytes"""
    return {path.relative_to(page_dir).as_posix(): path.read_bytes() for path in page_dir.rglob("*") if path.is_file()}


@pytest.mark.parametrize("compress", [True, False])
def test_pages_hold_the_merged_results(tmp_path: Path, compress: bool):
    """The cluster's merge (results_merger.py) gives the backend's merge, as float32, with a manifest of every object"""
    files = [str(path) for task_dir in TASK_DIRS for path in sorted(task_dir.glob("*.bdo"))]

    manifest = results_merger.write_directory(files, tmp_path, compress)

    expected = {estimator["name"]: estimator for estimator in merge_simulation_outputs(TASK_DIRS)}
    assert manifest["primaries"] == 400
    assert [estimator["name"] for estimator in manifest["estimators"]] == sorted(expected)
    for estimator in manifest["estimators"]:
        assert estimator["metadata"] == expected[estimator["name"]]["metadata"]
        for page, expected_page in zip(estimator["pages"], expected[estimator["name"]]["pages"], strict=True):
            page_dir = tmp_path / estimator["name"] / str(page["page_number"])
            objects = page_files(page_dir)
            assert {
                name: {"size": len(body), "md5": result_format.body_md5(body)} for name, body in objects.items()
            } == (page["files"])
            stored = result_format.json_page(*result_format.read_page(objects))
            values, expected_values = stored["data"].pop("values"), expected_page["data"]["values"]
            np.testing.assert_allclose(values, np.float32(expected_values), rtol=1e-7)
            assert stored == dict(expected_page, data={k: v for k, v in expected_page["data"].items() if k != "values"})


def test_one_estimator_at_a_time(monkeypatch):
    """An estimator's pages are handed on before the files of the next estimator are read, one file at a time"""
    events = []
    read = results_merger.read_estimator
    monkeypatch.setattr(
        results_merger, "read_estimator", lambda file: events.append(("read", Path(file).name)) or read(file)
    )

    def store(name, number, page, values):
        """Notes the page"""
        events.append(("store", name))
        return {}

    files = [str(path) for task_dir in TASK_DIRS for path in sorted(task_dir.glob("*.bdo"))]
    results_merger.write_pages(files, store)

    names = [name.rsplit("_", 1)[0] for kind, name in events if kind == "read"]
    stores = [name for kind, name in events if kind == "store"]
    # each estimator: its two task files read, then its pages stored, before the next one's files are read
    order = [(kind, name if kind == "store" else name.rsplit("_", 1)[0]) for kind, name in events]
    for estimator in sorted(set(stores)):
        first_store = order.index(("store", estimator))
        assert all(order.index(("read", other)) > first_store for other in names if other > estimator)
        assert names.count(estimator) == 2


def test_partial_merge_takes_the_latest_whole_save_of_every_task(tmp_path: Path):
    """The latest save named by its primaries; one still being copied (.<primaries>) is left out"""
    for task, task_dir in enumerate(TASK_DIRS, start=1):
        saves = tmp_path / f"task_{task}" / "saves"
        shutil.copytree(task_dir, saves / "100")
        shutil.copytree(task_dir, saves / "250")
        (saves / ".900").mkdir()
        (saves / ".900" / "broken.bdo").write_bytes(b"")

    files = results_merger.latest_saves(str(tmp_path / "task_*" / "saves"))

    assert files and all("/250/" in file for file in files)
    assert len(files) == sum(len(list(task_dir.glob("*.bdo"))) for task_dir in TASK_DIRS)


def test_merger_command_line(tmp_path: Path):
    """As the collect job runs it: patterns quoted, a manifest and pages written; nothing to merge fails"""
    output = tmp_path / "out"
    assert results_merger.main(["--output_dir", str(output), str(BDO_DIR / "task_*" / "*.bdo")]) == 0
    assert json.loads((output / "results.json").read_text())["estimators"]
    assert results_merger.main(["--output_dir", str(tmp_path / "none"), str(tmp_path / "*.bdo")]) == 1


def test_stdlib_reads_and_writes_pages_without_numpy(tmp_path: Path):
    """The uploader turns convertmc's JSON into pages with the standard library only (a cluster's plain Python)"""
    script = (
        "import sys, json; sys.modules['numpy'] = None; sys.modules['zstandard'] = None; "
        f"sys.path.insert(0, {str(Path(result_format.__file__).parent)!r}); import result_format as rf; "
        "files = rf.page_files({'dimensions': 1, 'data': {'unit': 'Gy', 'name': 'dose'}}, [0.0] * 70000 + [1.5]); "
        "page, values = rf.read_page(files); "
        "assert values[-1] == 1.5 and len(values) == 70001 and page['data']['unit'] == 'Gy'; "
        "assert 'zstd' not in files['zarr.json'].decode()"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_pages_open_with_zarr(tmp_path: Path):
    """Any Zarr v3 reader opens a page: zarr-python here, zarrita.js in the browser"""
    zarr = pytest.importorskip("zarr")
    values = np.zeros(200_000)
    values[123_456] = 2.5
    values[:10] = np.arange(10)
    for compress in (True, False):
        page_dir = tmp_path / str(compress)
        for name, body in result_format.page_files({"dimensions": 1, "data": {}}, values, compress).items():
            (page_dir / name).parent.mkdir(parents=True, exist_ok=True)
            (page_dir / name).write_bytes(body)
        array = zarr.open_array(str(page_dir), mode="r")
        np.testing.assert_array_equal(array[:], values.astype(np.float32))
        assert array.attrs["yaptide_page"] == {"dimensions": 1, "data": {}}


def test_empty_chunks_are_left_out():
    """A sparse result takes little space even without compression: chunks of zeros are only marked in the index"""
    values = np.zeros(10 * result_format.CHUNK_ITEMS)
    values[5] = 1.0
    files = result_format.page_files({"dimensions": 1, "data": {}}, values, compress=False)
    assert len(files["c/0"]) == result_format.CHUNK_ITEMS * result_format.ITEM_SIZE + 10 * 16


def render_partial(root: Path) -> str:
    """The partial script as the submit writes it"""
    return PARTIAL_SHIELDHIT_BASH.format(
        root_dir=root,
        sim_id=1,
        update_key="key",
        backend_url="https://yaptide.test",
        find_merge_python=FIND_MERGE_PYTHON,
    )


@pytest.mark.parametrize("has_pymchelper", [True, False])
def test_partial_script_merges_the_latest_saves_and_frees_the_lock(tmp_path: Path, has_pymchelper: bool):
    """The partial script merges the tasks' latest saves and uploads them as partial results, with a Python that has
    pymchelper; without one it does nothing. Either way it frees the lock its watcher took
    """
    (tmp_path / "partial.lock").mkdir()
    script = tmp_path / "partial_script.sh"
    script.write_text(render_partial(tmp_path))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    (bin_dir / "python3").write_text(
        f'#!/bin/bash\n[ "$1" = -c ] && exit {0 if has_pymchelper else 1}\necho "$@" >> {calls}\n'
    )
    (bin_dir / "python3").chmod(0o755)
    (bin_dir / "nice").write_text('#!/bin/bash\nshift 2\n"$@"\n')
    (bin_dir / "nice").chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)], env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "partial.lock").exists()
    if has_pymchelper:
        merge, upload = calls.read_text().splitlines()
        assert "results_merger.py" in merge and f"--latest_saves={tmp_path}/workspaces/task_*/saves" in merge
        assert "results_uploader.py --partial" in upload and "--sim_id=1" in upload
    else:
        assert not calls.exists()


def test_uploader_reads_the_merger_manifest(tmp_path: Path):
    """What results_merger.py wrote is what the uploader uploads, without converting"""
    results_merger.main(["--output_dir", str(tmp_path), str(BDO_DIR / "task_*" / "*.bdo")])
    manifest, pages_dir = results_uploader.read_results(tmp_path)
    assert pages_dir == tmp_path and manifest == json.loads((tmp_path / "results.json").read_text())


def test_backend_merge_puts_pages_into_storage_as_they_are_merged(monkeypatch):
    """A direct simulation's merge stores each page under one revision as it goes; the estimators point at them. A
    storage failure sends the rest to the database, as JSON pages
    """
    from yaptide.engine.simulation import PageWriter
    from yaptide.persistence import result_storage

    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    stored = {}
    monkeypatch.setattr(
        result_storage, "put_page_files", lambda prefix, files: stored.update({prefix: files}) or len(files)
    )
    writer = PageWriter(7)

    estimators = merge_simulation_outputs(TASK_DIRS, writer)

    pages = [page for estimator in estimators for page in estimator["pages"]]
    assert all(page["stored"]["format"] == result_format.FORMAT for page in pages)
    assert {page["stored"]["key"] for page in pages} == set(stored) == set(writer.written)
    assert all(f"/{writer.revision}/" in key and key.startswith("simulations/7/") for key in stored)

    def down(prefix, files):
        """Storage not answering"""
        raise ConnectionError(prefix)

    monkeypatch.setattr(result_storage, "put_page_files", down)
    estimators = merge_simulation_outputs(TASK_DIRS, PageWriter(7))
    assert all("values" in page["data"] for estimator in estimators for page in estimator["pages"])
