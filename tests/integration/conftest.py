import json
import logging
from pathlib import Path
import os
from typing import Generator
from flask import Flask
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
def app() -> Generator[Flask, None, None]:
    _app = create_app()
    with _app.app_context():
        db.create_all()
    yield _app

    with _app.app_context():
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    _client = app.test_client()
    yield _client
