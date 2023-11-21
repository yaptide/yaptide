import copy
import json
import logging
from pathlib import Path
import platform
from typing import Generator
import pytest
import os

from yaptide.application import create_app
from yaptide.persistence.database import db


@pytest.fixture(scope='session')
def shieldhit_binary_filename() -> str:
    """Name of the binary file for SHIELD-HIT12A"""
    binary_filename = "shieldhit"
    if platform.system() == 'Windows':
        return binary_filename + ".exe"
    return binary_filename


@pytest.fixture(scope='session')
def project_json_path() -> Generator[Path, None, None]:
    """Path to JSON project file"""
    main_dir = Path(__file__).resolve().parent.parent
    logging.debug("Main dir %s", main_dir)
    yield main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope='session')
def project_json_data(project_json_path: Path) -> Generator[dict, None, None]:
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
def payload_editor_dict_data(payload_editor_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not payload_editor_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(payload_editor_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def payload_editor_dict_data_fluka(payload_editor_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary

    It also sets sim_type to fluka.
    """
    json_data = {}
    if not payload_editor_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(payload_editor_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    payload_dict = copy.deepcopy(json_data)
    payload_dict['sim_type'] = 'fluka'
    yield payload_dict


@pytest.fixture(scope='session')
def shieldhit_payload_files_dict_path() -> Generator[Path, None, None]:
    """Path to payload file with simulation defined as user uploaded files"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "shieldhit_json_payload_files.json"


@pytest.fixture(scope='session')
def payload_files_dict_data(shieldhit_payload_files_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not shieldhit_payload_files_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(shieldhit_payload_files_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def fluka_payload_files_dict_path() -> Generator[Path, None, None]:
    """Path to payload file with simulation defined as user uploaded files"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "fluka_json_payload_files.json"


@pytest.fixture(scope='session')
def payload_files_dict_data(fluka_payload_files_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not fluka_payload_files_dict_path.suffix == '.json':
        raise ValueError("Payload file must be JSON file")
    with open(fluka_payload_files_dict_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope='session')
def result_dict_path() -> Generator[dict, None, None]:
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
        db.drop_all()
        db.create_all()
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


def check_if_environment_variables_set(variables: list[str]) -> bool:
    """Check if environment variables are set"""
    result = True
    for var_name in variables:
        if var_name not in os.environ:
            logging.error('variable %s not set', var_name)
            result = False
    return result
