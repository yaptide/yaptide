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

# the results bucket of the tests, emptied by them; created on the S3 server below if missing
TEST_BUCKET = "yaptide-results-test"


@pytest.fixture(scope="session", autouse=True)
def results_bucket() -> Generator[str, None, None]:
    """An S3 bucket for result pages, required by the backend: the server RESULTS_S3_ENDPOINT points at (e.g. a
    Garage container in CI, with its keys set), otherwise an in-process S3 mock (moto) started for the session
    """
    server = None
    if not os.environ.get("RESULTS_S3_ENDPOINT"):
        from moto.server import ThreadedMotoServer

        server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
        server.start()
        host, port = server.get_host_and_port()
        os.environ["RESULTS_S3_ENDPOINT"] = f"http://{host}:{port}"
        os.environ.setdefault("RESULTS_S3_ACCESS_KEY", "test")
        os.environ.setdefault("RESULTS_S3_SECRET_KEY", "test")
        # the mock creates buckets without a location only in the default region
        os.environ.setdefault("RESULTS_S3_REGION", "us-east-1")
    # always a bucket of its own: the tests empty it, so never a bucket of a deployment the environment points at
    os.environ["RESULTS_S3_BUCKET"] = TEST_BUCKET
    # the address the browser's signed links point to
    os.environ["BACKEND_EXTERNAL_URL"] = "https://yaptide.test"
    os.environ.pop("RESULTS_S3_PUBLIC_ENDPOINT", None)

    from botocore.exceptions import ClientError
    from yaptide.persistence import result_storage

    try:
        result_storage._internal().head_bucket(Bucket=result_storage.bucket())
    except ClientError:
        result_storage._internal().create_bucket(Bucket=result_storage.bucket())
    yield result_storage.bucket()
    empty_results_bucket()
    if server:
        server.stop()
        result_storage._client.cache_clear()


def empty_results_bucket() -> None:
    """Removes every result page from the test bucket"""
    from yaptide.persistence import result_storage

    result_storage._delete_listed(result_storage._internal(), result_storage.PAGE_PREFIX)  # skipcq: PYL-W0212


@pytest.fixture(autouse=True)
def results_bucket_emptied(results_bucket: str) -> Generator[None, None, None]:
    """Every test starts with no result pages in the bucket (simulation ids repeat in every new database); emptied
    before the test, as a test may leave the storage patched until its own teardown
    """
    empty_results_bucket()
    yield


@pytest.fixture(scope="session")
def shieldhit_binary_filename() -> str:
    """Name of the binary file for SHIELD-HIT12A"""
    binary_filename = "shieldhit"
    if platform.system() == "Windows":
        return binary_filename + ".exe"
    return binary_filename


@pytest.fixture(scope="session")
def project_json_path() -> Generator[Path, None, None]:
    """Path to JSON project file"""
    main_dir = Path(__file__).resolve().parent.parent
    logging.debug("Main dir %s", main_dir)
    yield main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope="session")
def project_json_data(project_json_path: Path) -> Generator[dict, None, None]:
    """Reads project JSON file and returns its contents as dictionary"""
    json_data = {}
    if not project_json_path.suffix == ".json":
        raise ValueError("Payload file must be JSON file")
    with open(project_json_path, "r") as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope="session")
def payload_editor_dict_path() -> Generator[Path, None, None]:
    """Path to payload JSON file"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "json_payload_editor.json"


@pytest.fixture(scope="session")
def payload_editor_dict_data(payload_editor_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not payload_editor_dict_path.suffix == ".json":
        raise ValueError("Payload file must be JSON file")
    with open(payload_editor_dict_path, "r") as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope="session")
def payload_editor_dict_data_fluka(payload_editor_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file and returns its contents as dictionary

    It also sets sim_type to fluka.
    """
    json_data = {}
    if not payload_editor_dict_path.suffix == ".json":
        raise ValueError("Payload file must be JSON file")
    with open(payload_editor_dict_path, "r") as file_handle:
        json_data = json.load(file_handle)
    payload_dict = copy.deepcopy(json_data)
    payload_dict["sim_type"] = "fluka"
    yield payload_dict


@pytest.fixture(scope="session")
def shieldhit_payload_files_dict_path() -> Generator[Path, None, None]:
    """Path to payload file with shieldhit simulation defined as user uploaded files"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "shieldhit_json_payload_files.json"


@pytest.fixture(scope="session")
def payload_files_dict_data(shieldhit_payload_files_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file for shieldhit and returns its contents as dictionary"""
    json_data = {}
    if not shieldhit_payload_files_dict_path.suffix == ".json":
        raise ValueError("Payload file must be JSON file")
    with open(shieldhit_payload_files_dict_path, "r") as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope="session")
def fluka_payload_files_dict_path() -> Generator[Path, None, None]:
    """Path to payload file with fluka simulation defined as user uploaded files"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "fluka_json_payload_files.json"


@pytest.fixture(scope="session")
def fluka_payload_files_dict_data(fluka_payload_files_dict_path: Path) -> Generator[dict, None, None]:
    """Reads payload JSON file for fluka and returns its contents as dictionary"""
    json_data = {}
    if not fluka_payload_files_dict_path.suffix == ".json":
        raise ValueError("Payload file must be JSON file")
    with open(fluka_payload_files_dict_path, "r") as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope="session")
def result_dict_path() -> Generator[dict, None, None]:
    """Path to json file with simulation results"""
    main_dir = Path(__file__).resolve().parent
    yield main_dir / "res" / "json_with_results.json"


@pytest.fixture(scope="session")
def result_dict_data(result_dict_path: Path) -> Generator[Path, None, None]:
    """Reads payload JSON file and returns its contents as dictionary"""
    json_data = {}
    if not result_dict_path.suffix == ".json":
        raise ValueError("Result file must be JSON file")
    with open(result_dict_path, "r") as file_handle:
        json_data = json.load(file_handle)
    yield json_data


@pytest.fixture(scope="function")
def db_session():
    """Creates database session. For each test function new clean database is created"""
    logging.debug("Database path %s", os.environ["FLASK_SQLALCHEMY_DATABASE_URI"])
    _app = create_app()
    with _app.app_context():
        db.drop_all()
        db.create_all()
        yield db.session
        db.drop_all()


@pytest.fixture(scope="session")
def db_good_username() -> str:
    """Username for user with valid password"""
    return "Gandalf"


@pytest.fixture(scope="session")
def db_good_password() -> str:
    """Password for user with valid password"""
    return "YouShallNotPass"


@pytest.fixture(scope="session")
def db_bad_username() -> str:
    """Username for user with invalid password"""
    return "Sauron"


def check_if_environment_variables_set(variables: list[str]) -> bool:
    """Check if environment variables are set"""
    result = True
    for var_name in variables:
        if var_name not in os.environ:
            logging.error("variable %s not set", var_name)
            result = False
    return result
