"""Every migration goes up and back down on Postgres, and the data migrations carry old data over
(set TEST_DATABASE_URI to an empty Postgres database; SQLite cannot run the migrations' foreign key changes)"""

import gzip
import json
import os

import flask_migrate
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from yaptide.application import create_app

URI = os.environ.get("TEST_DATABASE_URI", "")
pytestmark = pytest.mark.skipif(not URI.startswith("postgresql"), reason="the migrations need Postgres")

# the revision before the data migrations, and the latest one
BEFORE_DATA_MIGRATIONS = "4027fc5cbcb1"


@pytest.fixture
def app(monkeypatch):
    """App on an empty Postgres database, emptied again afterwards"""
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", URI)
    # a migration waiting on a lock fails the test instead of hanging it
    monkeypatch.setenv("PGOPTIONS", "-c lock_timeout=10000")
    app = create_app()
    with app.app_context():
        assert not tables(), f"{URI} is not empty"
        yield app
        flask_migrate.downgrade(revision="base")
        with engine().begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def engine():
    """An engine of its own, without a pool: no read here holds a lock a migration waits for"""
    return create_engine(URI, poolclass=NullPool)


def tables() -> list[str]:
    """Tables in the database, other than alembic's"""
    with engine().connect() as connection:
        return sorted(name for name in inspect(connection).get_table_names() if name != "alembic_version")


def query(sql: str) -> list:
    """Rows of a query, read in a connection closed right after"""
    with engine().connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def test_every_migration_goes_up_and_down(app):
    """From an empty database to the latest revision, back to nothing, and up again"""
    flask_migrate.upgrade()
    created = tables()
    assert "PageObject" in created and "Simulation" in created
    assert query("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal") == [("simulation_engine_events",)]

    flask_migrate.downgrade(revision="base")
    assert tables() == []

    flask_migrate.upgrade()
    assert tables() == created


def test_data_migrations_carry_old_data_over(app):
    """Estimators get their file names and readable names, pages their name and dimension from their data"""
    flask_migrate.upgrade(revision=BEFORE_DATA_MIGRATIONS)
    packed = lambda value: gzip.compress(json.dumps(value).encode())  # noqa: E731
    with engine().begin() as connection:
        connection.execute(text("""INSERT INTO "User" (id, username, auth_provider) VALUES (1, 'u', 'YaptideUser')"""))
        connection.execute(
            text(
                """INSERT INTO "Simulation" (id, job_id, user_id, start_time, title, platform, input_type, sim_type,
                job_state) VALUES (1, 'j', 1, now(), 't', 'DIRECT', 'FILES', 'shieldhit', 'COMPLETED')"""
            )
        )
        connection.execute(
            text(
                """INSERT INTO "Estimator" (id, simulation_id, name, compressed_data) VALUES (1, 1, 'z_profile_', :d)"""
            ),
            {"d": packed({"metadata": 1})},
        )
        page = {"dimensions": 1, "metadata": {"name": "dose", "page_number": 0}}
        connection.execute(
            text("""INSERT INTO "Page" (id, estimator_id, page_number, compressed_data) VALUES (1, 1, 0, :d)"""),
            {"d": packed(page)},
        )

    flask_migrate.upgrade()

    assert query('SELECT name, file_name FROM "Estimator"') == [("z_profile", "z_profile_")]
    assert query('SELECT page_name, page_dimension FROM "Page"') == [("dose", 1)]

    flask_migrate.downgrade(revision=BEFORE_DATA_MIGRATIONS)
    assert query('SELECT name FROM "Estimator"') == [("z_profile_",)]
