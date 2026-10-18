"""Schema preparation at startup: migrations where the database has them, tables plus a stamp on a new one"""

from unittest import mock

import flask_migrate
import pytest
from alembic.script import ScriptDirectory
from flask import current_app
from sqlalchemy import inspect, text

from yaptide.application import create_app
from yaptide.persistence.database import db
from yaptide.persistence.models import prepare_database

# the revision before the PageObject table, the partial results columns and Cluster.busy_until
PREVIOUS = "5003b9acb1f4"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """App on its own database file, as a deployment has"""
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'yaptide.db'}")
    app = create_app()
    with app.app_context():
        yield app


def version() -> str:
    """Revision the database is marked with"""
    return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def head() -> str:
    """Latest revision in the migrations directory"""
    config = current_app.extensions["migrate"].migrate.get_config()
    return ScriptDirectory.from_config(config).get_current_head()


def test_new_database_gets_tables_and_is_marked_current(app):
    """A new database is created from the models and later migrations start from the latest revision"""
    prepare_database()

    assert inspect(db.engine).has_table("PageObject")
    assert version() == head()


def test_database_under_migrations_is_migrated(app):
    """A table added by a migration is created by that migration, without clashing with the models"""
    db.create_all()
    db.session.execute(text('DROP TABLE "PageObject"'))
    db.session.execute(text('ALTER TABLE "Simulation" DROP COLUMN partial_primaries'))
    db.session.execute(text('ALTER TABLE "Simulation" DROP COLUMN partial_time'))
    db.session.execute(text('ALTER TABLE "Simulation" DROP COLUMN progress_revision'))
    db.session.execute(text('ALTER TABLE "Cluster" DROP COLUMN busy_until'))
    db.session.commit()
    flask_migrate.stamp(revision=PREVIOUS)

    # created by its migration: tables created from the models would hide migrations that only add columns
    with mock.patch.object(db, "create_all") as create_all:
        prepare_database()

    create_all.assert_not_called()
    assert inspect(db.engine).has_table("PageObject")
    assert {"partial_primaries", "partial_time"} <= {
        column["name"] for column in inspect(db.engine).get_columns("Simulation")
    }
    assert "busy_until" in {column["name"] for column in inspect(db.engine).get_columns("Cluster")}
    assert version() == head()


def test_preparing_twice_changes_nothing(app):
    """Every start of the backend prepares the schema again"""
    prepare_database()
    prepare_database()

    assert version() == head()
