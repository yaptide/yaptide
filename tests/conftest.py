"""
We have 3 types of JSON files:
1. Project JSON - file that could be generated using UI and saved using "Save project" button
  - examples of such files are in https://github.com/yaptide/ui/tree/master/src/ThreeEditor/examples
    or in yaptide_tester/example.json
  - this file can contain only simulation input in JSON format or results as well
  - top level keys: "metadata", "project", "scene", and others...

2. Payload JSON - object which is sent to the server using POST request from UI
  - all such objects contain "input_files" or "input_json" top level key

  a) editor payload JSON type assumes that user defined the simulation using UI 3D Editor and selected it for running
    - examples of such files are in tests/res/json_payload_editor.json
    - inside "input_json" key we have contents of project json file
  b) files payload JSON type assumes that user uploaded input files and selected them for running
    - examples of such files are in tests/res/json_payload_files.json
    - inside "input_files" key we have dictionary with filenames as keys and contents of input files as values

We assume following convention: `editor_dict`, `payload_editor_dict`, `payload_files_dict` and `payload_dict`

`editor_dict['metadata']`, `editor_dict['scene']` is always valid
`editor_dict['input_type']` is not valid

`payload_dict` can be either `payload_editor_dict` or `payload_files_dict`
`payload_dict['input_type']` is always valid

Therefore `payload_editor_dict['input_json']` can be passed as `editor_dict`,
 `payload_editor_dict['input_json']['metadata']` is valid
 `payload_editor_dict['input_json']['scene']` is valid
 `payload_editor_dict['input_json']['beam.dat']` is not valid
 `payload_editor_dict['input_files']['beam.dat']` is not valid

Therefore for `payload_files_dict['input_files']`,
 `payload_files_dict['input_files']['metadata']` is not valid
 `payload_files_dict['input_files']['beam.dat']` is valid
 `payload_editor_dict['input_json']['metadata']` is not valid

 We have as well `files_dict` where keys are filenames and values are contents of input files
 `files_dict[beam.dat]` is valid
"""

import json
import logging
from pathlib import Path
from typing import Generator
import pytest
import os

from yaptide.application import create_app
from yaptide.persistence.database import db


@pytest.fixture(scope='session')
def project_json_path() -> Generator[Path, None, None]:
    """Path to JSON project file"""
    main_dir = Path(__file__).resolve().parent.parent
    logging.debug("Main dir %s", main_dir)
    yield main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope='session')
def project_json_data(project_json_path: Path) -> Generator[Path, None, None]:
    """Reads project JSON file and returns its contents as dictionary"""
    json_data = {}
    if not project_json_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(project_json_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def payload_editor_dict_path() -> Generator[Path, None, None]:
    """Path to payload JSON file"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "json_payload_editor.json"


@pytest.fixture(scope='session')
def payload_editor_dict_data(payload_editor_dict_path: Path) -> Generator[Path, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not payload_editor_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(payload_editor_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def payload_files_dict_path() -> Generator[Path, None, None]:
    """Path to payload file with simulation defined as user uploaded files"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "json_payload_files.json"


@pytest.fixture(scope='session')
def payload_files_dict_data(payload_files_dict_path: Path) -> Generator[Path, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not payload_files_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(payload_files_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def result_dict_path() -> Generator[Path, None, None]:
    """Path to json file with simulation results"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "json_with_results.json"


@pytest.fixture(scope='session')
def result_dict_data(result_dict_path: Path) -> Generator[Path, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not result_dict_path.suffix == '.json':
        raise ValueError("Result file must be JSON file")
    with open(result_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='function')
def db_session():
    """Creates database session. For each test function new clean database is created"""
    logging.debug("Database path %s", os.environ['FLASK_SQLALCHEMY_DATABASE_URI'])
    _app = create_app()
    with _app.app_context():
        yield db.session
        db.drop_all()


@pytest.fixture(scope='session')
def db_good_username() -> str:
    """Username for user with valid password"""
    return "Gandalf"


@pytest.fixture(scope='session')
def db_good_password() -> str:
    """Password for user with valid password"""
    return "YouShallNotPass"


@pytest.fixture(scope='session')
def db_bad_username() -> str:
    """Username for user with invalid password"""
    return "Sauron"
