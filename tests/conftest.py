import json
import logging
from pathlib import Path
import platform
import pytest

"""
Notepad :
We have 3 types of JSON files:
1. Project JSON - file that could be generated using UI and saved using "Save project" button
  - examples of such files are in https://github.com/yaptide/ui/tree/master/src/ThreeEditor/examples or in yaptide_tester/example.json
  - this file can contain only simulation input in JSON format or results as well
  - top level keys: "metadata", "project", "scene", TODO

2. Payload JSON - object which is sent to the server using POST request from UI
  - all such objects contain "sim_data" top level key

  a) editor payload JSON type assumes that user defined completely the simulation using UI 3D Editor and selected it for running
    - examples of such files are in tests/res/json_editor_payload.json
    - inside "sim_data" key we have contents of project json file
  b) files payload JSON type assumes that user uploaded input files and selected them for running
    - examples of such files are in tests/res/json_files_payload.json
    - inside "sim_data" key we have dictionary with filenames as keys and contents of input files as values
 
In the source code we assume following convention: `editor_dict`, `payload_editor_dict`, `payload_files_dict` and `payload_dict` 

`editor_dict['metadata']`, `editor_dict['scene']` is always valid
`editor_dict['sim_data']` is not valid

`payload_dict` can be either `payload_editor_dict` or `payload_files_dict`
`payload_dict['sim_data']` is always valid

Therefore `payload_editor_dict['sim_data']` can be passed as `editor_dict`,
 `payload_editor_dict['sim_data']['metadata']` is valid
 `payload_editor_dict['sim_data']['scene']` is valid
 `payload_editor_dict['sim_data']['beam.dat']` is not valid

Therefore for `payload_files_dict['sim_data']`,
 `payload_files_dict['sim_data']['metadata']` is not valid
 `payload_files_dict['sim_data']['beam.dat']` is valid

 We have as well `files_dict` where keys are filenames and values are contents of input files
 `files_dict[beam.dat]` is valid
"""


@pytest.fixture(scope='session')
def project_json_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent.parent
    logging.debug("Main dir %s", main_dir)
    return main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope='session')
def project_json_data(project_json_path) -> dict:
    json_data = {}
    with open(project_json_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.fixture(scope='session')
def payload_editor_dict_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent
    return main_dir / "res" / "json_editor_payload.json"


@pytest.fixture(scope='session')
def payload_editor_dict_data(payload_editor_dict_path) -> dict:
    json_data = {}
    with open(payload_editor_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.fixture(scope='session')
def payload_files_dict_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent
    return main_dir / "res" / "json_files_payload.json"


@pytest.fixture(scope='session')
def payload_files_dict_data(payload_files_dict_path) -> dict:
    json_data = {}
    with open(payload_files_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.fixture(scope='session')
@pytest.mark.skipif(platform.system() != 'Linux', reason="SHIELDHIT demo binary is only supported on Linux.")
def shieldhit_demo_binary():
    from yaptide.admin.simulators import installation_path, install_simulator, SimulatorType
    shieldhit_bin_path = installation_path / 'shieldhit'
    if not shieldhit_bin_path.exists():
        install_simulator(SimulatorType.shieldhit)

@pytest.fixture(scope='session')
def add_directory_to_path():
    import os
    project_main_dir = Path(__file__).resolve().parent.parent
    bin_dir = project_main_dir / 'bin'
    logging.info("Adding %s to PATH", bin_dir)
    os.environ['PATH'] = f'{bin_dir}:' + os.environ['PATH']