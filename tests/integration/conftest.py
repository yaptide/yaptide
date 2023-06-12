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
def shieldhit_demo_binary():
    """Checks if SHIELD-HIT12A binary is installed and installs it if necessary"""
    from yaptide.admin.simulators import installation_path, install_simulator, SimulatorType
    shieldhit_bin_path = installation_path / 'shieldhit'
    # check if on Windows
    if os.name == 'nt':
        # append exe extension to the path
        shieldhit_bin_path = shieldhit_bin_path.with_suffix('.exe')
    logging.info("SHIELDHIT binary path %s", shieldhit_bin_path)
    if not shieldhit_bin_path.exists():
        install_simulator(SimulatorType.shieldhit)


@pytest.fixture(scope='session')
def yaptide_bin_dir() -> Generator[Path, None, None]:
    """directory with SHIELD-HIT12A executable file"""
    project_main_dir = Path(__file__).resolve().parent.parent.parent
    yield project_main_dir / 'bin'


@pytest.fixture(scope='function')
def add_directory_to_path(yaptide_bin_dir : Path):
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
