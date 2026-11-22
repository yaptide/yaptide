import os
from pathlib import Path

import pytest
from pytest import param

from yaptide.batch.fluka_string_templates import ARRAY_FLUKA_BASH
from yaptide.celery.utils.pymc import command_to_run_fluka
from yaptide.utils.enums import SimulationType
from yaptide.utils.sim_utils import (
    adjust_primaries_for_fluka_files,
    adjust_primaries_in_files_dict,
    get_simulator_type_and_particle_source_input_file,
    get_total_number_of_primaries,
    missing_particle_source_input_file,
    write_simulation_input_files,
)

SHIELDHIT_FILES = {
    "beam.dat": "NSTAT 10000 0\nEND\n",
    "geo.dat": "geo",
    "mat.dat": "mat",
    "detect.dat": "detect",
}
FLUKA_FILES = {"fl_sim.inp": "START         5000.0\nSTOP\n"}
FLUKA_COPY = {"fl_sim (1).inp": "START         1.0\nSTOP\n"}


@pytest.mark.parametrize(
    "start_line, tasks, expected",
    [
        param("START         50000.0", 1, "START         50000.", id="1 task"),
        param("START         50000.0", 2, "START         25000.", id="2 tasks"),
        param("START         50000.0", 3, "START         16666.", id="3 tasks"),
    ],
)
def test_adjust_primaries_for_fluka_files(start_line: str, tasks: int, expected: str):
    """Test that primary particles are correctly adjusted for FLUKA input files."""
    payload_files_dict = {"input_files": {"fl_sim.inp": f"{start_line}\n"}}
    expected = f"{expected}\n"

    files_dict, total_primaries = adjust_primaries_for_fluka_files(payload_files_dict=payload_files_dict, ntasks=tasks)

    assert len(files_dict) == 1
    assert total_primaries == 50000
    assert files_dict["fl_sim.inp"] == expected


def files_payload(sim_type: str, input_files: dict, ntasks: int = 4) -> dict:
    """Payload of a simulation run from input files."""
    return {"sim_type": sim_type, "input_type": "files", "ntasks": ntasks, "input_files": input_files}


@pytest.mark.parametrize(
    "sim_type, input_files, expected",
    [
        param(
            "fluka", {**SHIELDHIT_FILES, **FLUKA_FILES}, (SimulationType.FLUKA, "fl_sim.inp"), id="fluka with beam.dat"
        ),
        param("fluka", {**FLUKA_COPY, **FLUKA_FILES}, (SimulationType.FLUKA, "fl_sim.inp"), id="fluka with a copy"),
        param(
            "shieldhit",
            {**FLUKA_FILES, **SHIELDHIT_FILES},
            (SimulationType.SHIELDHIT, "beam.dat"),
            id="shieldhit with fl_sim.inp",
        ),
        param("fluka", {**SHIELDHIT_FILES, **FLUKA_COPY}, (None, None), id="fluka without fl_sim.inp"),
        param("shieldhit", FLUKA_FILES, (None, None), id="shieldhit without beam.dat"),
        param("topas", FLUKA_FILES, (None, None), id="simulator without a primaries file"),
        param("unknown", FLUKA_FILES, (None, None), id="unknown simulator"),
    ],
)
def test_particle_source_file_follows_sim_type(sim_type: str, input_files: dict, expected: tuple):
    """The file with primaries is chosen by sim_type and its exact name, whatever other files are sent."""
    assert get_simulator_type_and_particle_source_input_file(files_payload(sim_type, input_files)) == expected


def test_fluka_primaries_with_files_of_other_simulators():
    """Only START in fl_sim.inp is read and split between tasks, other files stay unchanged."""
    input_files = {**SHIELDHIT_FILES, **FLUKA_COPY, **FLUKA_FILES, "notes.txt": "x"}
    payload = files_payload("fluka", input_files)

    files_dict, total_primaries = adjust_primaries_in_files_dict(payload)

    assert get_total_number_of_primaries(payload) == 5000
    assert total_primaries == 5000
    assert files_dict["fl_sim.inp"].split()[:2] == ["START", "1250."]
    assert {name: content for name, content in files_dict.items() if name != "fl_sim.inp"} == {
        name: content for name, content in input_files.items() if name != "fl_sim.inp"
    }


def test_shieldhit_primaries_with_files_of_other_simulators():
    """Only NSTAT in beam.dat is read and split between tasks, fl_sim.inp stays unchanged."""
    payload = files_payload("shieldhit", {**FLUKA_FILES, **SHIELDHIT_FILES})

    files_dict, total_primaries = adjust_primaries_in_files_dict(payload)

    assert total_primaries == 10000
    assert files_dict["beam.dat"].split()[:2] == ["NSTAT", "2500"]
    assert files_dict["fl_sim.inp"] == FLUKA_FILES["fl_sim.inp"]


@pytest.mark.parametrize(
    "payload, expected",
    [
        param(files_payload("fluka", {**SHIELDHIT_FILES, **FLUKA_COPY}), "fl_sim.inp", id="fluka"),
        param(files_payload("shieldhit", FLUKA_FILES), "beam.dat", id="shieldhit"),
        param(files_payload("fluka", {**SHIELDHIT_FILES, **FLUKA_FILES}), None, id="present"),
        param(files_payload("topas", {}), None, id="simulator without a primaries file"),
        param({"sim_type": "fluka", "input_type": "editor", "input_json": {}}, None, id="editor"),
    ],
)
def test_missing_particle_source_input_file(payload: dict, expected):
    """The required file with primaries is reported only for runs from input files."""
    assert missing_particle_source_input_file(payload) == expected


@pytest.fixture
def rfluka_in_path(tmp_path_factory, monkeypatch) -> None:
    """Puts a fake rfluka executable in PATH."""
    bin_dir = tmp_path_factory.mktemp("bin")
    rfluka = bin_dir / "rfluka"
    rfluka.write_text("#!/bin/sh\n")
    rfluka.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.mark.usefixtures("rfluka_in_path")
def test_command_to_run_fluka_uses_fl_sim_inp(tmp_path: Path):
    """FLUKA runs fl_sim.inp even when other .inp files are in the directory."""
    write_simulation_input_files({"a.inp": "START 1.0\n", **FLUKA_COPY, **FLUKA_FILES}, tmp_path)

    command = command_to_run_fluka(dir_path=tmp_path, task_id=1)

    assert command[-1] == str(tmp_path / "fl_sim.inp")
    assert (tmp_path / "a.inp").read_text() == "START 1.0\n"


def test_command_to_run_fluka_without_fl_sim_inp(tmp_path: Path):
    """Without fl_sim.inp the command cannot be created."""
    write_simulation_input_files(FLUKA_COPY, tmp_path)

    with pytest.raises(FileNotFoundError):
        command_to_run_fluka(dir_path=tmp_path, task_id=1)


def test_fluka_batch_script_runs_fl_sim_inp():
    """The batch script copies all input files and runs fl_sim.inp."""
    script = ARRAY_FLUKA_BASH.format(
        array_header="",
        root_dir="/root",
        sim_id=1,
        update_key="key",
        backend_url="",
        fluka_input_file="fl_sim.inp",
    )

    assert "cp $INPUT_DIR/* ." in script
    assert "INPUT_FILE=fl_sim.inp" in script
    assert "rfluka -N0 -M1 $WORK_DIR/$INPUT_FILE" in script
    assert "*.inp" not in script


@pytest.mark.parametrize("filename", ["../x.inp", "/tmp/x.inp", "a/b.inp", "..", ".", ""])
def test_write_simulation_input_files_rejects_paths(tmp_path, filename: str):
    """Test that filenames escaping the output directory are rejected."""
    with pytest.raises(ValueError):
        write_simulation_input_files({filename: "x"}, tmp_path)


def test_write_simulation_input_files_keeps_unicode_names(tmp_path):
    """Test that non-ASCII filenames are written unchanged."""
    write_simulation_input_files({"原子.inp": "x"}, tmp_path)
    assert (tmp_path / "原子.inp").read_text() == "x"
