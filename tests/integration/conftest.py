import copy
import datetime
import logging
from pathlib import Path
import os
import platform
import subprocess
from typing import Generator
import pytest
# skipcq: PY-W2000
from celery.contrib.pytest import celery_app, celery_worker, celery_enable_logging, celery_config, celery_parameters, use_celery_app_trap, celery_includes, celery_worker_pool
from yaptide.admin.simulator_storage import download_shieldhit_from_s3_or_from_website
from yaptide.application import create_app


@pytest.fixture(scope='session')
def small_simulation_payload(payload_editor_dict_data: dict) -> Generator[dict, None, None]:
    """Small simulation payload for testing purposes"""
    payload_dict = copy.deepcopy(payload_editor_dict_data)

    # limit the particle numbers to get faster results
    payload_dict["ntasks"] = 2
    payload_dict["input_json"]["beam"]["numberOfParticles"] = 12

    # reduce number of segments to get results which are easier to print
    for detector in payload_dict["input_json"]["detectorManager"]["detectors"]:
        for segments_type in ["xSegments", "ySegments", "zSegments"]:
            # if segments_type is missing (for example xSegments is missing for cylinder detector)
            # then we skip it by comparing default value 2 > 1
            if detector["geometryData"]["parameters"].get(segments_type, 2) > 1:
                detector["geometryData"]["parameters"][segments_type] = 4
    # reduce number of bins to get results which are easier to print
    for scoring in payload_dict["input_json"]["scoringManager"]["outputs"]:
        for quantity in scoring["quantities"]:
            for modifier in quantity["modifiers"]:
                if modifier.get("binsNumber", 2) > 1:
                    modifier["binsNumber"] = 4

    if platform.system() == "Windows":
        payload_dict["input_json"]["scoringManager"]["filters"] = []
        payload_dict["input_json"]["detectorManager"]["detectors"] = [
            payload_dict["input_json"]["detectorManager"]["detectors"][0]
        ]
        payload_dict["input_json"]["scoringManager"]["outputs"] = [
            payload_dict["input_json"]["scoringManager"]["outputs"][0]
        ]
        for output in payload_dict["input_json"]["scoringManager"]["outputs"]:
            for quantity in output["quantities"]:
                if "filter" in quantity:
                    del quantity["filter"]
    yield payload_dict


@pytest.fixture(scope='session')
def shieldhit_binary_installed(shieldhit_binary_filename):
    """Checks if SHIELD-HIT12A binary is installed and installs it if necessary"""
    download_dir = Path(__file__).resolve().parent.parent.parent / 'bin'
    shieldhit_bin_path = download_dir / shieldhit_binary_filename
    logging.info("SHIELD-HIT12A binary path %s", shieldhit_bin_path)
    if not shieldhit_bin_path.exists():
        download_shieldhit_from_s3_or_from_website(
            destination_dir=download_dir,
            endpoint=os.environ.get('S3_ENDPOINT'),
            access_key=os.environ.get('S3_ACCESS_KEY'),
            secret_key=os.environ.get('S3_SECRET_KEY'),
            password=os.environ.get('S3_ENCRYPTION_PASSWORD'),
            salt=os.environ.get('S3_ENCRYPTION_SALT'),
            bucket=os.environ.get('S3_SHIELDHIT_BUCKET'),
            key=os.environ.get('S3_SHIELDHIT_KEY'),
            decrypt=True,
        )


@pytest.fixture(scope='session')
def yaptide_bin_dir():
    """directory with simulators executable files"""
    project_main_dir = Path(__file__).resolve().parent.parent.parent
    yield project_main_dir / 'bin'


@pytest.fixture(scope='function')
def add_simulators_to_path_variable(yaptide_bin_dir):
    """Adds bin directory with simulators executable file to PATH"""
    logging.info("Adding %s to PATH", yaptide_bin_dir)

    # Get the current PATH value
    original_path = os.environ.get("PATH", "")

    # Update the PATH with the new directory
    os.environ['PATH'] = f'{yaptide_bin_dir}' + os.pathsep + os.environ['PATH']

    # Yield control back to the test
    yield

    # Restore the original PATH
    os.environ['PATH'] = original_path


@pytest.fixture(scope='session')
def yaptide_fake_dir() -> Generator[Path, None, None]:
    """directory with mocks of simulator executable files"""
    project_main_dir = Path(__file__).resolve().parent.parent.parent
    yield project_main_dir / 'yaptide' / 'fake'


@pytest.fixture(scope='function')
def add_simulator_mocks_to_path_variable(yaptide_fake_dir: Path):
    """Adds bin directory with mocks of simulators executable file to PATH"""
    logging.info("Adding %s to PATH", yaptide_fake_dir)

    # Get the current PATH value
    original_path = os.environ.get("PATH", "")

    # Update the PATH with the new directory
    os.environ['PATH'] = f'{yaptide_fake_dir}' + os.pathsep + os.environ['PATH']

    # Yield control back to the test
    yield

    # Restore the original PATH
    os.environ['PATH'] = original_path


@pytest.fixture(scope="function")
def celery_worker_parameters() -> Generator[dict, None, None]:
    """Here we could as well configure other fixture simulation-worker parameters, like app, pool, loglevel, etc."""
    logging.info("Creating celery simulation-worker parameters for testing")

    # get current logging level
    log_level = logging.getLogger().getEffectiveLevel()

    yield {
        "concurrency": 2,
        "loglevel": log_level,  # set celery simulation-worker log level to the same as the one used by pytest
        "queues": ('simulations'),
        'perform_ping_check': False  # it's crucial for tests to pass. There is bug in celery related to using queues.
    }


@pytest.fixture(scope='session')
def celery_enable_logging():
    return True


@pytest.fixture(scope='function')
def modify_tmpdir(tmpdir_factory):
    """
    In yaptide some of the modules (pymchelper?) uses temporary directories to store files.
    This is convenient in production, but in testing we want to have a control over the temporary directory path.
    This fixture replaces the default temporary directory paths with the one provided by tmpdir_factory fixture.
    Under Linux temporary directory is usually /tmp
    Python uses env variables TMPDIR, TEMP and TMP to store the temporary directory path.

    pytest on contrary has smarter way of handling temporary directories, which is provided by tmpdir_factory fixture.
    It doesn't remove the temporary directory after the test is done, but keeps last 3 of them.
    This fixture replaces the env variables TMPDIR, TEMP and TMP
    with the temporary directory path provided by tmpdir_factory.
    """
    # Get the temporary directory path from the tmpdir fixture
    tmpdir = tmpdir_factory.getbasetemp()

    # Store the original TMPDIR value
    original_tmpdir = os.environ.get('TMPDIR')
    original_temp = os.environ.get('TEMP')
    original_tmp = os.environ.get('TMP')

    # Set the TMPDIR environment variable to the temporary directory path
    logging.info("Replacing old value %s of TMPDIR with %s", original_tmpdir, tmpdir)
    os.environ['TMPDIR'] = str(tmpdir)
    logging.info("Replacing old value %s of TEMP with %s", original_temp, tmpdir)
    os.environ['TEMP'] = str(tmpdir)
    logging.info("Replacing old value %s of TMP with %s", original_tmp, tmpdir)
    os.environ['TMP'] = str(tmpdir)

    yield

    # Restore the original TMPDIR value after the tests are done
    if original_tmpdir is None:
        del os.environ['TMPDIR']
    else:
        os.environ['TMPDIR'] = original_tmpdir
    if original_temp is None:
        del os.environ['TEMP']
    else:
        os.environ['TEMP'] = original_temp
    if original_tmp is None:
        del os.environ['TMP']
    else:
        os.environ['TMP'] = original_tmp


@pytest.fixture(autouse=True)
def clear_celery_queue(celery_app):
    yield
    celery_app.control.purge()


@pytest.fixture(scope="function")
def app(tmp_path):
    """Create Flask app for testing"""
    # for some unknown reasons Flask live server and celery won't work with the default in-memory database
    # so we need to create a temporary database file
    # for each new test a new temporary directory is created
    sqlite_db_path = Path(tmp_path) / 'main.db'
    # ensure the sqlite file doesn't exist, remove if exists
    if sqlite_db_path.exists():
        logging.info("Removing old sqlite database file %s", sqlite_db_path)
        sqlite_db_path.unlink()

    # Store the original TMPDIR value
    old_db_uri = os.environ.get('FLASK_SQLALCHEMY_DATABASE_URI')
    new_db_uri = f'sqlite:///{tmp_path}/main.db'
    logging.debug("Replacing old value %s of FLASK_SQLALCHEMY_DATABASE_URI with %s", old_db_uri, new_db_uri)
    os.environ['FLASK_SQLALCHEMY_DATABASE_URI'] = new_db_uri

    logging.info("Creating Flask app for testing, time = %s", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    from yaptide.persistence.database import db
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    # clean up the database
    with app.app_context():
        db.drop_all()

    # revert the FLASK_SQLALCHEMY_DATABASE_URI to the original value
    if old_db_uri is None:
        del os.environ['FLASK_SQLALCHEMY_DATABASE_URI']
    else:
        os.environ['FLASK_SQLALCHEMY_DATABASE_URI'] = old_db_uri


def pytest_collection_modifyitems(config, items):  # skipcq: PYL-W0613
    """Conditionally remove live_server fixture from tests on Windows and MacOS"""
    if platform.system() == 'Linux':
        # Remove live_server_win fixture from tests on Linux
        for item in items:
            if 'live_server_win' in item.fixturenames:
                item.fixturenames.remove('live_server_win')
    else:
        # Remove live_server fixture from tests on Windows and MacOS
        for item in items:
            if 'live_server' in item.fixturenames:
                item.fixturenames.remove('live_server')


@pytest.fixture(scope="function")
def live_server_win():
    """
    Ideally we would use live_server fixture from pytest-flask library for all operating systems.
    Unfortunately, it doesn't work on Windows, so we need to create our own fixture.
    See an issue https://github.com/pytest-dev/pytest-flask/issues/54#issuecomment-535885042
    This fixture is condionally used only on Windows.
    """
    logging.debug("Creating live_server_win fixture")
    env = os.environ.copy()
    env["FLASK_APP"] = "yaptide.application"
    server = subprocess.Popen(['flask', 'run', '--port', '5000'], env=env)  # skipcq: BAN-B607
    try:
        yield server
    finally:
        server.terminate()
