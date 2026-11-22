"""Old result pages copied from the database to object storage as Zarr, cleared there only when verified, and moved
back

SQLite by default, an empty Postgres with TEST_DATABASE_URI; the bucket of tests/conftest.py.
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
from yaptide.batch import result_format
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import CelerySimulationModel, EstimatorModel, PageModel, YaptideUserModel
from yaptide.utils.enums import EntityState, InputType, SimulationType

POSTGRES = os.environ.get("TEST_DATABASE_URI", "")


def old_page(name: str, page_number: int, sim_id: int) -> dict:
    """A page as the database kept it before the bucket"""
    return {
        "data": {"values": [page_number + 0.5, sim_id], "unit": "Gy"},
        "dimensions": 1,
        "metadata": {"name": name, "page_number": page_number},
    }


@pytest.fixture
def database(tmp_path, monkeypatch) -> str:
    """Database with two finished simulations of 12 old pages, kept in it; their objects removed afterwards"""
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
                        estimator_id=estimator.id, page_number=page_number, page_dimension=1, page_name=name
                    )
                    page.data = old_page(name, page_number, simulation.id)
                    db.session.add(page)
        db.session.commit()
        db.session.remove()
        yield uri
        for sim_id in (1, 2):
            result_storage.delete_simulation(sim_id)
        db.session.remove()
        db.drop_all()


def run(*args: str, ok: bool = True):
    """Runs a db_manage command, which connects to the database on its own"""
    result = CliRunner().invoke(db_manage.run, list(args))
    assert (result.exit_code == 0) == ok, result.output
    return result


def engine():
    """An engine of its own on the test database"""
    return create_engine(os.environ["FLASK_SQLALCHEMY_DATABASE_URI"], poolclass=NullPool)


def database_hash() -> str:
    """Hash of every row of every table"""
    metadata = MetaData()
    metadata.reflect(bind=engine())
    digest = hashlib.sha256()
    with engine().connect() as connection:
        for name in sorted(metadata.tables):
            table = metadata.tables[name]
            for row in connection.execute(select(table).order_by(*table.primary_key.columns)):
                digest.update(repr((name, tuple(row))).encode())
    return digest.hexdigest()


def scalar(sql: str):
    """The single value a query gives"""
    with engine().connect() as connection:
        return connection.exec_driver_sql(sql).scalar()


def stored_prefixes(sim_id: int) -> set[str]:
    """Prefixes of the pages in the bucket of a simulation"""
    listing = result_storage._internal().list_objects_v2(  # skipcq: PYL-W0212
        Bucket=result_storage.bucket(), Prefix=f"simulations/{sim_id}/"
    )
    return {
        item["Key"].removesuffix(result_format.METADATA_FILE)
        for item in listing.get("Contents", [])
        if item["Key"].endswith(result_format.METADATA_FILE)
    }


def page_prefix(page_id: int) -> str:
    """Where the page is in storage, as the database says"""
    return scalar(f'SELECT key FROM "PageObject" WHERE page_id = {page_id}')


def test_interrupted_and_repeated_copy_leaves_the_database_identical(database, monkeypatch):
    """A copy stopped half way and repeated, twice, changes nothing in the database and uploads each page once"""
    before = database_hash()
    put = result_storage.put_page_files
    uploads = []

    def interrupted(prefix, files):
        """Uploads two pages, then stops as Ctrl-C would"""
        if len(uploads) == 2:
            raise KeyboardInterrupt
        uploads.append(prefix)
        return put(prefix, files)

    monkeypatch.setattr(result_storage, "put_page_files", interrupted)
    run("copy-pages-to-storage", "--batch-size", "5", ok=False)
    assert database_hash() == before
    monkeypatch.setattr(result_storage, "put_page_files", put)

    assert "10 uploaded in this run" in run("copy-pages-to-storage", "--batch-size", "5").output
    assert ", 0 uploaded in this run" in run("copy-pages-to-storage").output
    assert "12 of 12 pages already in storage, 0 to upload" in run("copy-pages-to-storage", "--dry-run").output
    assert database_hash() == before
    assert len(stored_prefixes(1)) == len(stored_prefixes(2)) == 6


def test_clear_refuses_a_batch_not_all_in_storage(database):
    """A missing object stops the clear before its batch; earlier batches are cleared and point at their copies"""
    run("copy-pages-to-storage")
    before = database_hash()
    # the shard of the last page of the second simulation
    last = max(stored_prefixes(2), key=lambda prefix: ("fluence/2/" in prefix, prefix))
    result_storage._internal().delete_object(  # skipcq: PYL-W0212
        Bucket=result_storage.bucket(), Key=last + result_format.SHARD_FILE
    )

    output = run("clear-pages-in-postgres", "--dry-run", ok=False).output
    assert "1 pages of this batch are not in storage" in output
    assert database_hash() == before

    run("clear-pages-in-postgres", "--batch-size", "6", ok=False)
    assert scalar('SELECT count(*) FROM "Page" WHERE compressed_data IS NULL') == 6
    assert scalar('SELECT count(*) FROM "PageObject"') == 6
    assert page_prefix(1) in stored_prefixes(1)


def test_clear_and_move_back_give_the_same_pages(database):
    """Copy, clear and move back: the backend reads the Zarr copies in between, and afterwards the database holds
    every page again (values as float32), so the migration can go down again
    """
    run("copy-pages-to-storage")
    run("clear-pages-in-postgres", "--batch-size", "5")
    assert scalar('SELECT count(*) FROM "Page" WHERE compressed_data IS NOT NULL') == 0

    app = create_app()
    with app.app_context():
        page = db.session.query(PageModel).filter_by(estimator_id=1, page_number=1).one()
        assert page.stored_object.format == result_storage.ZARR_FORMAT
        assert page.stored_object.key.startswith("simulations/1/dose/1/")
        files = result_storage.get_page_files(page.stored_object.key)
        assert page.stored_object.size == sum(len(body) for body in files.values())
        assert result_format.json_page(*result_format.read_page(files)) == old_page("dose", 1, 1)
        db.session.remove()

    run("move-pages-to-postgres", "--batch-size", "5")
    assert scalar('SELECT count(*) FROM "PageObject"') == 0
    with engine().connect() as connection:
        rows = connection.exec_driver_sql(
            'SELECT "Page".page_number, "Page".compressed_data, "Estimator".name, "Estimator".simulation_id '
            'FROM "Page" JOIN "Estimator" ON "Page".estimator_id = "Estimator".id'
        ).all()
    assert len(rows) == 12
    for page_number, body, name, sim_id in rows:
        assert json.loads(gzip.decompress(body)) == old_page(name, page_number, sim_id)


def test_every_page_gets_a_prefix_of_its_own(database):
    """Two estimators with the same file name and pages with the same data still get their own copies, so clearing
    or replacing one never touches another
    """
    app = create_app()
    with app.app_context():
        estimator = EstimatorModel(name="again", file_name="dose", simulation_id=1)
        db.session.add(estimator)
        db.session.commit()
        page = PageModel(estimator_id=estimator.id, page_number=0, page_dimension=1, page_name="dose")
        page.data = old_page("dose", 0, 1)
        db.session.add(page)
        db.session.commit()
        db.session.remove()

    assert "13 uploaded in this run" in run("copy-pages-to-storage").output
    run("clear-pages-in-postgres")

    assert len({page_prefix(page_id) for page_id in range(1, 14)}) == 13
    assert {page_prefix(page_id) for page_id in range(1, 14)} == stored_prefixes(1) | stored_prefixes(2)


def backend_stores(page: dict) -> str:
    """The backend storing new results of the first page under a new revision, as POST /results does"""
    prefix = result_storage.page_prefix(1, "dose", 0, result_storage.new_revision())
    size = result_storage.put_page_files(
        prefix, result_format.page_files(dict(page, data={"unit": "Gy"}), page["data"]["values"])
    )
    with engine().begin() as connection:
        connection.exec_driver_sql('UPDATE "Page" SET compressed_data = NULL WHERE id = 1')
        connection.exec_driver_sql('DELETE FROM "PageObject" WHERE page_id = 1')
        connection.exec_driver_sql(
            f"INSERT INTO \"PageObject\" (page_id, key, size, format) VALUES (1, '{prefix}', {size}, 'zarr-v3')"
        )
    return prefix


def set_state(job_state: str) -> None:
    """Sets the state of the first simulation"""
    with engine().begin() as connection:
        connection.exec_driver_sql(f"UPDATE \"Simulation\" SET job_state = '{job_state}' WHERE id = 1")


def test_unfinished_simulations_are_left_to_the_backend(database):
    """Neither the copy nor the clear touches a running simulation, whose pages the backend may replace any time"""
    set_state(EntityState.RUNNING.value)

    assert "6 pages" in run("copy-pages-to-storage").output
    run("clear-pages-in-postgres")

    assert stored_prefixes(1) == set()
    # the six pages of the running simulation
    assert scalar('SELECT count(*) FROM "Page" WHERE compressed_data IS NOT NULL') == 6


def test_move_keeps_a_page_the_backend_stored_meanwhile(database, monkeypatch):
    """A page stored again by the backend after the move read it keeps the new results, moved by the next run"""
    run("copy-pages-to-storage")
    run("clear-pages-in-postgres")
    set_state(EntityState.RUNNING.value)
    new = old_page("dose", 0, 99)
    get = result_storage.get_page_files
    read = []

    def backend_meanwhile(prefix):
        """The backend stores the first page again, after the move read it"""
        files = get(prefix)
        if not read:
            read.append(prefix)
            backend_stores(new)
        return files

    monkeypatch.setattr(result_storage, "get_page_files", backend_meanwhile)
    assert "1 pages changed meanwhile and stay in storage" in run("move-pages-to-postgres", "--batch-size", "5").output
    assert scalar('SELECT count(*) FROM "Page" WHERE compressed_data IS NULL') == 1
    run("move-pages-to-postgres")
    assert scalar('SELECT count(*) FROM "Page" WHERE compressed_data IS NULL') == 0
    body = scalar('SELECT compressed_data FROM "Page" WHERE id = 1')
    assert json.loads(gzip.decompress(body)) == new
