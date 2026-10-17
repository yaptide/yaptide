"""Old result pages copied from the database to object storage, cleared there only when verified, and moved back

SQLite and storage in a dict by default; with TEST_DATABASE_URI (an empty Postgres) and RESULTS_S3_BUCKET,
RESULTS_S3_ENDPOINT and its keys set, the same tests run against them.
"""

import gzip
import hashlib
import json
import os

import pytest
from click.testing import CliRunner
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.pool import NullPool

from yaptide.admin import db_manage
from yaptide.application import create_app
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    CelerySimulationModel,
    EstimatorModel,
    PageModel,
    PageObjectModel,
    YaptideUserModel,
)
from yaptide.utils.enums import EntityState, InputType, SimulationType

POSTGRES = os.environ.get("TEST_DATABASE_URI", "")
REAL_STORAGE = bool(os.environ.get("RESULTS_S3_ENDPOINT"))


@pytest.fixture
def database(tmp_path, monkeypatch) -> str:
    """Database with two simulations of 12 old pages, kept in it"""
    uri = POSTGRES if POSTGRES.startswith("postgresql") else f"sqlite:///{tmp_path / 'yaptide.db'}"
    monkeypatch.setenv("FLASK_SQLALCHEMY_DATABASE_URI", uri)
    app = create_app()
    with app.app_context():
        db.create_all()
        user = YaptideUserModel(username="Gandalf", password_hash="-")
        db.session.add(user)
        db.session.commit()
        for number in range(2):
            simulation = CelerySimulationModel(
                job_id=f"old{number}",
                user_id=user.id,
                input_type=InputType.FILES.value,
                sim_type=SimulationType.SHIELDHIT.value,
                title="old",
                job_state=EntityState.COMPLETED.value,
            )
            db.session.add(simulation)
            db.session.commit()
            for name in ("dose", "fluence"):
                estimator = EstimatorModel(name=name, file_name=name, simulation_id=simulation.id)
                db.session.add(estimator)
                db.session.commit()
                for page_number in range(3):
                    page = PageModel(
                        estimator_id=estimator.id, page_number=page_number, page_dimension=1, page_name="p"
                    )
                    page.data = {"data": {"values": [page_number, simulation.id]}, "name": name}
                    db.session.add(page)
        db.session.commit()
        db.session.remove()
        yield uri
        db.session.remove()
        db.drop_all()


@pytest.fixture
def storage(monkeypatch) -> dict:
    """Object storage: the configured one, emptied afterwards, or one kept in a dict"""
    objects = {}
    if REAL_STORAGE:
        yield objects
        result_storage.delete_objects("simulations/")
        return
    monkeypatch.setenv("RESULTS_S3_BUCKET", "results")
    monkeypatch.setattr(result_storage, "put_gzipped_page", objects.__setitem__)
    monkeypatch.setattr(result_storage, "get_gzipped_page", objects.__getitem__)
    monkeypatch.setattr(result_storage, "delete_objects", objects.pop)
    monkeypatch.setattr(
        result_storage,
        "stored_matches",
        lambda key, size, md5: key in objects and result_storage.body_md5(objects[key]) == md5,
    )
    yield objects


def run(*args: str, ok: bool = True):
    """Runs a db_manage command, which connects to the database on its own"""
    result = CliRunner().invoke(db_manage.run, list(args))
    assert (result.exit_code == 0) == ok, result.output
    return result


def database_hash(uri: str) -> str:
    """Hash of every row of every table"""
    engine = create_engine(uri, poolclass=NullPool)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    digest = hashlib.sha256()
    with engine.connect() as connection:
        for name in sorted(metadata.tables):
            table = metadata.tables[name]
            for row in connection.execute(select(table).order_by(*table.primary_key.columns)):
                digest.update(repr((name, tuple(row))).encode())
    return digest.hexdigest()


def page_rows(uri: str, where: str) -> int:
    """How many pages match the condition"""
    engine = create_engine(uri, poolclass=NullPool)
    with engine.connect() as connection:
        return connection.exec_driver_sql(f'SELECT count(*) FROM "Page" WHERE {where}').scalar()


def test_interrupted_and_repeated_copy_leaves_the_database_identical(database, storage, monkeypatch):
    """A copy stopped half way and repeated, twice, changes nothing in the database and uploads each page once"""
    before = database_hash(database)
    put = result_storage.put_gzipped_page
    uploads = []

    def interrupted(key, body):
        """Uploads two pages, then stops as Ctrl-C would"""
        if len(uploads) == 2:
            raise KeyboardInterrupt
        uploads.append(key)
        put(key, body)

    monkeypatch.setattr(result_storage, "put_gzipped_page", interrupted)
    run("copy-pages-to-storage", "--batch-size", "5", ok=False)
    assert database_hash(database) == before
    monkeypatch.setattr(result_storage, "put_gzipped_page", put)

    assert "10 uploaded in this run" in run("copy-pages-to-storage", "--batch-size", "5").output
    assert ", 0 uploaded in this run" in run("copy-pages-to-storage").output
    assert "12 of 12 pages already in storage, 0 to upload" in run("copy-pages-to-storage", "--dry-run").output
    assert database_hash(database) == before


def test_clear_refuses_a_batch_not_all_in_storage(database, storage):
    """A missing copy stops the clear before its batch; earlier batches are cleared and readable from storage"""
    run("copy-pages-to-storage")
    before = database_hash(database)
    # the last page of the second simulation
    result_storage.delete_objects(result_storage.page_key(2, "fluence", 2))

    output = run("clear-pages-in-postgres", "--dry-run", ok=False).output
    assert "1 pages of this batch are not in storage" in output
    assert database_hash(database) == before

    run("clear-pages-in-postgres", "--batch-size", "6", ok=False)
    assert page_rows(database, "compressed_data IS NULL") == 6
    assert page_rows(database, "compressed_data IS NOT NULL") == 6


def test_clear_and_move_back_restore_the_database(database, storage):
    """Copy, clear and move back give the very same database, so the migration can go down again"""
    before = database_hash(database)
    run("copy-pages-to-storage")
    run("clear-pages-in-postgres", "--batch-size", "5")
    assert page_rows(database, "compressed_data IS NOT NULL") == 0

    app = create_app()
    with app.app_context():
        page = db.session.query(PageModel).filter_by(estimator_id=1, page_number=1).one()
        assert page.stored_object.key == result_storage.page_key(1, "dose", 1)
        body = result_storage.get_gzipped_page(page.stored_object.key)
        assert json.loads(gzip.decompress(body)) == {"data": {"values": [1, 1]}, "name": "dose"}
        db.session.remove()

    run("move-pages-to-postgres", "--batch-size", "5")
    assert database_hash(database) == before


def test_copy_never_replaces_another_page(database, storage):
    """A key taken by a page kept only in storage, or by an earlier page (estimators with the same file name), is
    not uploaded to, and the pages behind it are not cleared
    """
    taken = result_storage.page_key(2, "fluence", 0)
    only_copy = gzip.compress(b'{"only": "copy"}')
    result_storage.put_gzipped_page(taken, only_copy)
    app = create_app()
    with app.app_context():
        page = PageModel(estimator_id=1, page_number=9, page_dimension=1, page_name="new")
        page.stored_object = PageObjectModel(key=taken, size=len(only_copy), format=result_storage.PAGE_FORMAT)
        estimator = EstimatorModel(name="again", file_name="dose", simulation_id=1)
        db.session.add_all([page, estimator])
        db.session.commit()
        page = PageModel(estimator_id=estimator.id, page_number=0, page_dimension=1, page_name="p")
        page.data = {"data": "other"}
        db.session.add(page)
        db.session.commit()
        db.session.remove()

    output = run("copy-pages-to-storage").output
    assert f"key {taken} belongs to another page, skipped" in output
    assert "key simulations/1/dose/0.json belongs to another page, skipped" in output
    assert "11 uploaded in this run" in output
    assert result_storage.get_gzipped_page(taken) == only_copy
    run("clear-pages-in-postgres", ok=False)
    assert page_rows(database, "compressed_data IS NOT NULL") == 13


def backend_stores(body: bytes) -> None:
    """The backend storing new results of the first page, as store_partial_results does with a bucket"""
    key = result_storage.page_key(1, "dose", 0)
    result_storage.put_gzipped_page(key, body)
    with create_engine(os.environ["FLASK_SQLALCHEMY_DATABASE_URI"], poolclass=NullPool).begin() as connection:
        connection.exec_driver_sql('UPDATE "Page" SET compressed_data = NULL WHERE id = 1')
        connection.exec_driver_sql('DELETE FROM "PageObject" WHERE page_id = 1')
        connection.exec_driver_sql(
            'INSERT INTO "PageObject" (page_id, key, size, format) VALUES (1, %s, %s, %s)'
            if connection.dialect.name == "postgresql"
            else 'INSERT INTO "PageObject" (page_id, key, size, format) VALUES (1, ?, ?, ?)',
            (key, len(body), result_storage.PAGE_FORMAT),
        )


def set_state(job_state: str) -> None:
    """Sets the state of the first simulation"""
    with create_engine(os.environ["FLASK_SQLALCHEMY_DATABASE_URI"], poolclass=NullPool).begin() as connection:
        connection.exec_driver_sql(f"UPDATE \"Simulation\" SET job_state = '{job_state}' WHERE id = 1")


def test_unfinished_simulations_are_left_to_the_backend(database, storage, monkeypatch):
    """The backend replacing a page of a running simulation during the copy keeps its new page: the copy and the
    clear touch only finished simulations
    """
    set_state(EntityState.RUNNING.value)
    new = gzip.compress(b'{"new": "results"}')
    matches = result_storage.stored_matches

    def backend_meanwhile(key, size, md5):
        """The backend stores the first page of the running simulation again, after the copy read it"""
        if not stored:
            stored.append(key)
            backend_stores(new)
        return matches(key, size, md5)

    stored = []
    monkeypatch.setattr(result_storage, "stored_matches", backend_meanwhile)
    run("copy-pages-to-storage")
    assert result_storage.get_gzipped_page(result_storage.page_key(1, "dose", 0)) == new
    monkeypatch.setattr(result_storage, "stored_matches", matches)
    run("clear-pages-in-postgres")
    # the other five pages of the running simulation
    assert page_rows(database, "compressed_data IS NOT NULL") == 5


def test_move_keeps_a_page_the_backend_stored_meanwhile(database, storage, monkeypatch):
    """A page stored again by the backend after the move read it keeps the new results, moved by the next run"""
    run("copy-pages-to-storage")
    run("clear-pages-in-postgres")
    set_state(EntityState.RUNNING.value)
    new = gzip.compress(b'{"new": "results"}')
    get = result_storage.get_gzipped_page

    def backend_meanwhile(key):
        """The backend stores the first page again, after the move read it"""
        body = get(key)
        if not read:
            read.append(key)
            backend_stores(new)
        return body

    read = []
    monkeypatch.setattr(result_storage, "get_gzipped_page", backend_meanwhile)
    assert "1 pages changed meanwhile and stay in storage" in run("move-pages-to-postgres", "--batch-size", "5").output
    assert page_rows(database, "compressed_data IS NULL") == 1
    run("move-pages-to-postgres")
    assert page_rows(database, "compressed_data IS NULL") == 0
    engine = create_engine(database, poolclass=NullPool)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT compressed_data FROM "Page" WHERE id = 1').scalar() == new
