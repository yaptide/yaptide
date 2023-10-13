import copy
import logging
from pathlib import Path
import os
import platform
import subprocess
from typing import Generator
import pytest

from yaptide.application import create_app
from yaptide.persistence.database import db


@pytest.fixture(scope='session')
def small_simulation_payload(payload_editor_dict_data : dict) -> Generator[dict, None, None]:
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
            payload_dict["input_json"]["detectorManager"]["detectors"][0]]
        payload_dict["input_json"]["scoringManager"]["outputs"] = [
            payload_dict["input_json"]["scoringManager"]["outputs"][0]]
        for output in payload_dict["input_json"]["scoringManager"]["outputs"]:
            for quantity in output["quantities"]:
                if "filter" in quantity:
                    del quantity["filter"]
    yield payload_dict


@pytest.fixture(scope='session')
def shieldhit_binary_installed(shieldhit_binary_filename):
    """Checks if SHIELD-HIT12A binary is installed and installs it if necessary"""
    from yaptide.admin.simulators import install_simulator, SimulatorType
    installation_path = Path(__file__).resolve().parent.parent.parent / 'bin'
    shieldhit_bin_path = installation_path / shieldhit_binary_filename
    logging.info("SHIELDHIT binary path %s", shieldhit_bin_path)
    if not shieldhit_bin_path.exists():
        install_simulator(SimulatorType.shieldhit, installation_path)


@pytest.fixture(scope='session')
def yaptide_bin_dir() -> Generator[Path, None, None]:
    """directory with SHIELD-HIT12A executable file"""
    project_main_dir = Path(__file__).resolve().parent.parent.parent
    yield project_main_dir / 'bin'


@pytest.fixture(scope='function')
def add_simulators_to_path_variable(yaptide_bin_dir : Path):
    """Adds bin directory with SHIELD-HIT12A executable file to PATH"""
    logging.info("Adding %s to PATH", yaptide_bin_dir)

    # Get the current PATH value
    original_path = os.environ.get("PATH", "")

    # Update the PATH with the new directory
    os.environ['PATH'] = f'{yaptide_bin_dir}' + os.pathsep + os.environ['PATH']

    # Yield control back to the test
    yield

    # Restore the original PATH
    os.environ['PATH'] = original_path


@pytest.fixture(scope='function')
def celery_app():
    """
    Create celery app for testing, we reuse the one from yaptide.celery.worker module.
    The choice of broker and backend is important, as we don't want to run external redis server.
    That is being configured via environment variables in pytest.ini file.
    """
    logging.info("Creating celery app for testing")
    from yaptide.celery.worker import celery_app as app
    # choose eventlet as a default pool, as it is the only one properly supporting cancellation of tasks
    app.conf.task_default_pool = 'eventlet'
    return app


@pytest.fixture(scope="function")
def celery_worker_parameters() -> Generator[dict, None, None]:
    """
    Default celery worker parameters cause problems with finding "ping task" module, as being described here:
    https://github.com/celery/celery/issues/4851#issuecomment-604073785
    To solve that issue we disable the ping check.
    Another solution would be to do `from celery.contrib.testing.tasks import ping` but current one is more elegant.

    Here we could as well configure other fixture worker parameters, like app, pool, loglevel, etc.
    """
    logging.info("Creating celery worker parameters for testing")

    # get current logging level
    log_level = logging.getLogger().getEffectiveLevel()

    yield {
        "perform_ping_check": False,
        "concurrency": 1,
        "loglevel": log_level,  # set celery worker log level to the same as the one used by pytest
    }


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
        del os.environ['TMP']
    else:
        os.environ['TMP'] = original_tmpdir
    if original_temp is None:
        del os.environ['TEMP']
    else:
        os.environ['TEMP'] = original_temp
    if original_tmp is None:
        del os.environ['TMPDIR']
    else:
        os.environ['TMPDIR'] = original_tmp


@pytest.fixture(scope="function")
def app(tmp_path):
    """Create Flask app for testing"""
    # for some unknown reasons Flask live server and celery won't work with the default in-memory database
    # so we need to create a temporary database file
    # for each new test a new temporary directory is created
    os.environ['FLASK_SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/main.db'
    logging.info("Database path %s", os.environ['FLASK_SQLALCHEMY_DATABASE_URI'])

    app = create_app()
    yield app

    with app.app_context():
        db.drop_all()


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
    env = os.environ.copy()
    env["FLASK_APP"] = "yaptide.application"
    server = subprocess.Popen(['flask', 'run', '--port', '5000'], env=env)  # skipcq: BAN-B607
    try:
        yield server
    finally:
        server.terminate()
