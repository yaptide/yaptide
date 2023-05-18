import logging
from pathlib import Path
import os
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
def add_directory_to_path():
    """Adds bin directory with SHIELD-HIT12A executable file to PATH"""
    project_main_dir = Path(__file__).resolve().parent.parent.parent
    bin_dir = project_main_dir / 'bin'
    logging.info("Adding %s to PATH", bin_dir)
    os.environ['PATH'] = f'{bin_dir}' + os.pathsep + os.environ['PATH']


@pytest.fixture(scope='function')
def client_fixture():
    """Flask client fixture for testing"""
    flask_app = create_app()

    # Create a test client using the Flask application configured for testing
    with flask_app.test_client() as testing_client:
        # Establish an application context
        with flask_app.app_context():
            db.create_all()

            yield testing_client  # this is where the testing happens!

            db.drop_all()


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
