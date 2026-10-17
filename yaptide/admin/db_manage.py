#! /usr/bin/env python
"""
This script is used to manage the database via a command line application.
It is supposed to be used outside of the docker container, therefore by purpose it has
no dependency on the yaptide package. All the tables used by ORM are defined here again.
We do not use ORM model classes here, because we do not want to import the yaptide package.
"""

from enum import Enum, auto
import gzip
import json
import os

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class TableTypes(Enum):
    """Enum for table names used in ORM"""

    User = auto()
    YaptideUser = auto()
    KeycloakUser = auto()
    Simulation = auto()
    Cluster = auto()
    Task = auto()
    Result = auto()
    Input = auto()
    Estimator = auto()
    Page = auto()
    PageObject = auto()


def connect_to_db(verbose: int = 0) -> tuple[db.Connection, db.MetaData, db.Engine]:
    """Connects to the db"""
    db_uri = os.environ.get("FLASK_SQLALCHEMY_DATABASE_URI")
    if not db_uri:
        click.echo(f"Database URI: {db_uri} not set - aborting", err=True)
        raise click.Abort()
    if verbose > 1:
        click.echo(f"Connecting to URI: {db.make_url(db_uri).render_as_string(hide_password=True)}")
    echo: bool = verbose > 1
    engine = db.create_engine(db_uri, echo=echo)
    try:
        con = engine.connect()
        metadata = db.MetaData()
        metadata.reflect(bind=engine)
    except db.exc.OperationalError:
        click.echo(f"Connection to db {db.make_url(db_uri).render_as_string(hide_password=True)} failed", err=True)
        raise click.Abort()
    return con, metadata, engine


def user_exists(name: str, auth_provider: str, users: db.Table, con) -> bool:
    """Check if user already exists"""
    stmt = db.select(users).filter_by(username=name, auth_provider=auth_provider)
    users_found = con.execute(stmt).all()
    if len(users_found) > 0:
        click.echo(f"User: {name} exists")
        return True
    return False


@click.group()
def run():
    """Manage database"""


@run.command
@click.option("-v", "--verbose", count=True)
def list_users(verbose):
    """List users"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    users = metadata.tables[TableTypes.User.name]
    stmt = db.select(users.c.username, users.c.auth_provider)
    all_users = con.execute(stmt).all()

    click.echo(f"{len(all_users)} users in DB:")
    for user in all_users:
        click.echo(f"Login {user.username}; Auth provider {user.auth_provider}")


@run.command
@click.argument("name")
@click.option("password", "--password", default="")
@click.option("-v", "--verbose", count=True)
def add_user(name, password, verbose):
    """Add yaptide user to database"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f"Adding user: {name}")
    if verbose > 2:
        click.echo(f"Password: {password}")

    users = metadata.tables[TableTypes.User.name]

    if user_exists(name=name, auth_provider="YaptideUser", users=users, con=con):
        click.echo(f"YaptideUser: {name} already exists, aborting add")
        raise click.Abort()

    click.echo(f"YaptideUser: {name} does not exist, adding")
    click.echo(f"Adding user: {name}")
    query = db.insert(users).values(username=name, auth_provider="YaptideUser")
    result = con.execute(query)
    user_id = result.inserted_primary_key[0]
    password_hash = generate_password_hash(password)

    yaptide_users = metadata.tables[TableTypes.YaptideUser.name]
    query = db.insert(yaptide_users).values(id=user_id, password_hash=password_hash)
    con.execute(query)
    con.commit()


@run.command
@click.argument("name")
@click.option("password", "--password", default="")
@click.option("-v", "--verbose", count=True)
def update_user(name, password, verbose):
    """Update user in database"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f"Updating user: {name}")
    users = metadata.tables[TableTypes.User.name]

    if not user_exists(name, "YaptideUser", users, con):
        click.echo(f"YaptideUser: {name} does not exist, aborting update")
        raise click.Abort()

    # update password
    if password:
        pwd_hash: str = generate_password_hash(password)
        yaptide_users = metadata.tables[TableTypes.YaptideUser.name]
        stmt = (
            db.update(yaptide_users)
            .where(yaptide_users.c.id == users.c.id)
            .where(users.c.username == name)
            .where(users.c.auth_provider == "YaptideUser")
            .values(password_hash=pwd_hash)
        )
        con.execute(stmt)
        con.commit()
        if verbose > 2:
            click.echo(f"Updating password: {password}")
    click.echo(f"Successfully updated user: {name}")


@run.command
@click.argument("name")
@click.argument("auth_provider")
def remove_user(name, auth_provider):
    """Delete user"""
    con, metadata, _ = connect_to_db()
    click.echo(f"Deleting user: {name}")
    users = metadata.tables[TableTypes.User.name]

    # abort if user does not exist
    if not user_exists(name, auth_provider, users, con):
        click.echo(f"Aborting, user {name} does not exist")
        raise click.Abort()

    if os.environ.get("RESULTS_S3_BUCKET"):
        # the database removes the user's simulations by cascade, their stored result pages have to go first
        from yaptide.persistence import result_storage

        simulations = metadata.tables[TableTypes.Simulation.name]
        user_ids = db.select(users.c.id).where(users.c.username == name, users.c.auth_provider == auth_provider)
        for (simulation_id,) in con.execute(db.select(simulations.c.id).where(simulations.c.user_id.in_(user_ids))):
            result_storage.delete_simulation(simulation_id)

    query = db.delete(users).where(users.c.username == name, users.c.auth_provider == auth_provider)
    con.execute(query)
    con.commit()
    click.echo(f"Successfully deleted user: {name}")


@run.command
@click.option("sim_id", "--sim_id")
@click.option("user", "--user")
@click.option("auth_provider", "--auth-provider")
def list_tasks(user, auth_provider, sim_id):
    """List tasks"""
    con, metadata, _ = connect_to_db()
    tasks = metadata.tables[TableTypes.Task.name]
    users = metadata.tables[TableTypes.User.name]
    simulations = metadata.tables[TableTypes.Simulation.name]

    if user:
        stmt = db.select(users).filter_by(username=user)
        users_found = con.execute(stmt).all()
        if not len(users_found) > 0:
            click.echo(f"Aborting, user {user} does not exist")
            raise click.Abort()

    filter_args_user = {}
    filter_args_simulation = {}

    if user:
        filter_args_user["username"] = user
    if auth_provider:
        filter_args_user["auth_provider"] = auth_provider
    if sim_id:
        filter_args_simulation["simulation_id"] = int(sim_id)

    stmt = (
        db.select(tasks.c.simulation_id, tasks.c.task_id, users.c.username, tasks.c.task_state)
        .select_from(tasks)
        .filter_by(**filter_args_simulation)
        .join(simulations, tasks.c.simulation_id == simulations.c.id)
        .join(users, simulations.c.user_id == users.c.id)
        .filter_by(**filter_args_user)
        .order_by(tasks.c.simulation_id, tasks.c.task_id)
    )
    all_tasks = con.execute(stmt).all()

    click.echo(f"{len(all_tasks)} tasks in DB:")
    for task in all_tasks:
        simulation_id_col = f"Simulation id {task.simulation_id}"
        task_id_col = f"Task id ...{task.task_id}"
        task_state_col = f"task_state {task.task_state}"
        user_col = f" username {task.username}" if not user else ""

        click.echo("; ".join((simulation_id_col, task_id_col, task_state_col, user_col)))


@run.command
@click.argument("simulation_id")
@click.argument("task_id")
@click.option("-v", "--verbose", count=True)
def remove_task(simulation_id, task_id, verbose):
    """Delete task"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f"Deleting task: {task_id} from simulation: {simulation_id}")
    tasks = metadata.tables[TableTypes.Task.name]
    simulation_id = int(simulation_id)
    task_id = int(task_id)

    stmt = db.select(tasks).filter_by(task_id=task_id, simulation_id=simulation_id)
    task_found = con.execute(stmt).all()
    if not task_found:
        click.echo(f"Aborting, task {task_id} does not exist")
        raise click.Abort()

    query = db.delete(tasks).where(tasks.c.task_id == task_id)
    con.execute(query)
    con.commit()
    click.echo(f"Successfully deleted task: {task_id}")


@run.command
@click.option("-v", "--verbose", count=True)
@click.option("user", "--user")
@click.option("auth_provider", "--auth-provider")
def list_simulations(verbose, user, auth_provider):
    """List simulations"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    simulations = metadata.tables[TableTypes.Simulation.name]
    users = metadata.tables[TableTypes.User.name]

    if user:
        stmt = db.select(users).filter_by(username=user)
        users_found = con.execute(stmt).all()
        if not len(users_found) > 0:
            click.echo(f"Aborting, user {user} does not exist")
            raise click.Abort()

    filter_args = {}

    if user:
        filter_args["username"] = user
    if auth_provider:
        filter_args["auth_provider"] = auth_provider

    stmt = (
        db.select(
            simulations.c.id, simulations.c.job_id, simulations.c.start_time, simulations.c.end_time, users.c.username
        )
        .select_from(simulations)
        .join(users, simulations.c.user_id == users.c.id)
        .filter_by(**filter_args)
    )
    sims = con.execute(stmt).all()

    click.echo(f"{len(sims)} simulations in DB:")
    user_column = ""
    for sim in sims:
        user_column = f" username {sim.username}" if not user else ""
        click.echo(
            f"id {sim.id}; job id {sim.job_id}; start_time {sim.start_time}; end_time {sim.end_time};{user_column}"
        )


@run.command
@click.argument("simulation_id")
@click.option("-v", "--verbose", count=True)
def remove_simulation(simulation_id, verbose):
    """Delete simulation"""
    simulation_id = int(simulation_id)
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f"Deleting simulation: {simulation_id}")
    simulations = metadata.tables[TableTypes.Simulation.name]

    stmt = db.select(simulations).filter_by(id=simulation_id)
    simulation_found = con.execute(stmt).all()
    if not simulation_found:
        click.echo(f"Aborting, simulation {simulation_id} does not exist")
        raise click.Abort()

    if os.environ.get("RESULTS_S3_BUCKET"):
        # result pages in object storage go first, like in the user's delete; imported only where results live there
        from yaptide.persistence import result_storage

        result_storage.delete_simulation(simulation_id)

    query = db.delete(simulations).where(simulations.c.id == simulation_id)

    con.execute(query)
    con.commit()
    click.echo(f"Successfully deleted simulation: {simulation_id}")


@run.command
@click.argument("cluster_name")
@click.option("-v", "--verbose", count=True)
def add_cluster(cluster_name, verbose):
    """Adds cluster with provided name to database if it does not exist"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    cluster_table = metadata.tables[TableTypes.Cluster.name]

    # check if cluster already exists
    stmt = db.select(cluster_table).filter_by(cluster_name=cluster_name)
    clusters = con.execute(stmt).all()
    if len(clusters) > 0:
        click.echo(f"Cluster {cluster_name} already exists in DB")
        raise click.Abort()

    stmt = db.insert(cluster_table).values(cluster_name=cluster_name)
    con.execute(stmt)
    con.commit()
    click.echo(f"Cluster {cluster_name} added to DB")


@run.command
def list_clusters():
    """List clusters"""
    con, metadata, _ = connect_to_db()
    stmt = db.select(metadata.tables[TableTypes.Cluster.name])
    clusters = con.execute(stmt).all()

    click.echo(f"{len(clusters)} clusters in DB:")
    for cluster in clusters:
        click.echo(f"id {cluster.id}; cluster name {cluster.cluster_name};")


def results_storage():
    """The result_storage module, when a results bucket is configured; imported only here, see the module docstring"""
    if not os.environ.get("RESULTS_S3_BUCKET"):
        click.echo("RESULTS_S3_BUCKET not set - aborting", err=True)
        raise click.Abort()
    from yaptide.persistence import result_storage

    return result_storage


def pages_in_postgres(con, metadata: db.MetaData, after_id: int, batch_size: int) -> list:
    """The next pages kept only in the database, by id: id, the page's object key parts and its gzipped data"""
    pages = metadata.tables[TableTypes.Page.name]
    estimators = metadata.tables[TableTypes.Estimator.name]
    objects = metadata.tables[TableTypes.PageObject.name]
    stmt = (
        db.select(
            pages.c.id,
            pages.c.page_number,
            pages.c.compressed_data,
            estimators.c.simulation_id,
            estimators.c.file_name,
        )
        .join(estimators, pages.c.estimator_id == estimators.c.id)
        .outerjoin(objects, objects.c.page_id == pages.c.id)
        .where(pages.c.compressed_data.is_not(None), objects.c.page_id.is_(None), pages.c.id > after_id)
        .order_by(pages.c.id)
        .limit(batch_size)
    )
    return con.execute(stmt).all()


def count_pages_in_postgres(con, metadata: db.MetaData) -> tuple[int, int]:
    """How many pages are kept only in the database, and their size in bytes"""
    pages = metadata.tables[TableTypes.Page.name]
    objects = metadata.tables[TableTypes.PageObject.name]
    stmt = (
        db.select(db.func.count(), db.func.coalesce(db.func.sum(db.func.length(pages.c.compressed_data)), 0))
        .select_from(pages)
        .outerjoin(objects, objects.c.page_id == pages.c.id)
        .where(pages.c.compressed_data.is_not(None), objects.c.page_id.is_(None))
    )
    return tuple(con.execute(stmt).one())


def lock_simulations(con, simulation_ids) -> None:
    """Waits for results of these simulations being stored by the backend, as it does (lock_results in
    yaptide/routes/common_sim_routes.py), so it reads the pages again after this transaction
    """
    if con.dialect.name == "postgresql":
        for simulation_id in sorted(set(simulation_ids)):
            con.execute(db.text("SELECT pg_advisory_xact_lock(:simulation_id)"), {"simulation_id": simulation_id})


def megabytes(size: int) -> str:
    """Size for the progress output"""
    return f"{size / 1e6:.1f} MB"


@run.command
@click.option("--batch-size", default=100, show_default=True, help="Pages read from the database at once")
@click.option("--dry-run", is_flag=True, help="Only check which pages are already in storage, upload nothing")
@click.option("-v", "--verbose", count=True)
def copy_pages_to_storage(batch_size, dry_run, verbose):
    """Copies result pages from the database to storage; the database keeps them.

    Each copy is checked in the results bucket (size and MD5). Only reads the database: the pages are still read
    from it until clear-pages-in-postgres. Can be stopped and repeated at any time; a page already in storage
    unchanged is not uploaded again.
    """
    result_storage = results_storage()
    con, metadata, _ = connect_to_db(verbose=verbose)
    # closed at the end, also when stopped: an open transaction would hold its locks until the process exits
    with con:
        objects = metadata.tables[TableTypes.PageObject.name]
        total, total_size = count_pages_in_postgres(con, metadata)
        click.echo(f"{total} pages ({megabytes(total_size)}) kept only in the database")
        done, uploaded, skipped, after_id = 0, 0, [], 0
        keys_seen = set()
        while batch := pages_in_postgres(con, metadata, after_id, batch_size):
            # read-only: end the transaction, so it holds nothing while the batch uploads
            con.rollback()
            after_id = batch[-1].id
            keys = {
                page.id: result_storage.page_key(page.simulation_id, page.file_name, page.page_number) for page in batch
            }
            # a key another page's object already has: uploading would replace the only copy of that page
            taken = set(con.execute(db.select(objects.c.key).where(objects.c.key.in_(keys.values()))).scalars())
            con.rollback()
            batch_size_bytes = 0
            for page in batch:
                key = keys[page.id]
                if key in taken or key in keys_seen:
                    skipped.append(page.id)
                    click.echo(f"Page {page.id}: key {key} belongs to another page, skipped", err=True)
                    continue
                keys_seen.add(key)
                body = page.compressed_data
                md5 = result_storage.body_md5(body)
                if not result_storage.stored_matches(key, len(body), md5):
                    if dry_run:
                        continue
                    result_storage.put_gzipped_page(key, body)
                    if not result_storage.stored_matches(key, len(body), md5):
                        raise click.ClickException(f"Page {page.id}: the copy in storage does not match ({key})")
                    uploaded += 1
                    batch_size_bytes += len(body)
                done += 1
            click.echo(
                f"up to page {after_id}: {done}/{total} in storage, {uploaded} uploaded in this run "
                f"(+{megabytes(batch_size_bytes)})"
            )
        if dry_run:
            click.echo(f"Dry run: {done} of {total} pages already in storage, {total - done - len(skipped)} to upload")
        if skipped:
            click.echo(f"{len(skipped)} pages skipped (keys taken), still only in the database: {skipped}", err=True)


@run.command
@click.option("--batch-size", default=100, show_default=True, help="Pages cleared in one transaction")
@click.option("--dry-run", is_flag=True, help="Only check that the pages are in storage, change nothing")
@click.option("-v", "--verbose", count=True)
def clear_pages_in_postgres(batch_size, dry_run, verbose):
    """Removes from the database the pages verified in storage (pg_dump first).

    Makes the copies made by copy-pages-to-storage the only ones: the pages are read from storage from now on.

    A batch is changed only when every page of it is in storage with the same size and MD5, then in one
    transaction; otherwise the command stops and that batch stays in the database. Undone by move-pages-to-postgres.
    """
    result_storage = results_storage()
    con, metadata, _ = connect_to_db(verbose=verbose)
    # closed at the end, also when stopped: an open transaction would hold its locks until the process exits
    with con:
        pages = metadata.tables[TableTypes.Page.name]
        objects = metadata.tables[TableTypes.PageObject.name]
        total, total_size = count_pages_in_postgres(con, metadata)
        click.echo(f"{total} pages ({megabytes(total_size)}) kept only in the database")
        cleared, changed, after_id = 0, [], 0
        while batch := pages_in_postgres(con, metadata, after_id, batch_size):
            con.rollback()
            after_id = batch[-1].id
            keys = {
                page.id: result_storage.page_key(page.simulation_id, page.file_name, page.page_number) for page in batch
            }
            missing = [
                page.id
                for page in batch
                if not result_storage.stored_matches(
                    keys[page.id], len(page.compressed_data), result_storage.body_md5(page.compressed_data)
                )
            ]
            if missing:
                raise click.ClickException(
                    f"{len(missing)} pages of this batch are not in storage as in the database, run "
                    f"copy-pages-to-storage first; nothing changed from page {batch[0].id} on: {missing}"
                )
            if dry_run:
                cleared += len(batch)
                continue
            with con.begin():
                lock_simulations(con, (page.simulation_id for page in batch))
                for page in batch:
                    # only if the backend did not store the page again since it was read
                    stmt = (
                        db.update(pages)
                        .where(pages.c.id == page.id, pages.c.compressed_data == page.compressed_data)
                        .values(compressed_data=None)
                    )
                    if con.execute(stmt).rowcount != 1:
                        changed.append(page.id)
                        continue
                    con.execute(
                        db.insert(objects).values(
                            page_id=page.id,
                            key=keys[page.id],
                            size=len(page.compressed_data),
                            format=result_storage.PAGE_FORMAT,
                        )
                    )
                    cleared += 1
            click.echo(f"up to page {after_id}: {cleared}/{total} cleared")
        if dry_run:
            click.echo(f"Dry run: all {cleared} pages are in storage and can be cleared")
        if changed:
            click.echo(f"{len(changed)} pages changed meanwhile and stay in the database: {changed}", err=True)


@run.command
@click.option("--batch-size", default=100, show_default=True, help="Pages written to the database in one transaction")
@click.option("--dry-run", is_flag=True, help="Only count the pages, change nothing")
@click.option("-v", "--verbose", count=True)
def move_pages_to_postgres(batch_size, dry_run, verbose):
    """Moves every result page kept in storage back into the database.

    The database reads the pages from itself again.

    Run before downgrading below the PageObject migration (c75a1d0e4f21), or to undo clear-pages-in-postgres.
    Each batch is one transaction; the objects stay in the bucket.
    """
    result_storage = results_storage()
    con, metadata, _ = connect_to_db(verbose=verbose)
    # closed at the end, also when stopped: an open transaction would hold its locks until the process exits
    with con:
        pages = metadata.tables[TableTypes.Page.name]
        estimators = metadata.tables[TableTypes.Estimator.name]
        objects = metadata.tables[TableTypes.PageObject.name]
        total, total_size = con.execute(
            db.select(db.func.count(), db.func.coalesce(db.func.sum(objects.c.size), 0))
        ).one()
        con.rollback()
        click.echo(f"{total} pages ({megabytes(total_size)}) kept in object storage")
        if dry_run:
            return
        moved = 0
        stmt = (
            db.select(objects.c.page_id, objects.c.key, objects.c.size, objects.c.format, estimators.c.simulation_id)
            .join(pages, pages.c.id == objects.c.page_id)
            .join(estimators, pages.c.estimator_id == estimators.c.id)
            .order_by(objects.c.page_id)
            .limit(batch_size)
        )
        while batch := con.execute(stmt).all():
            con.rollback()
            bodies = {}
            for page in batch:
                if page.format != result_storage.PAGE_FORMAT:
                    raise click.ClickException(
                        f"Page {page.page_id} is stored as {page.format}, which is not known here"
                    )
                body = result_storage.get_gzipped_page(page.key)
                # the size it was stored with, and a whole gzip (its CRC) of JSON
                if len(body) != page.size:
                    raise click.ClickException(
                        f"Page {page.page_id}: {page.key} has {len(body)} bytes, not {page.size}"
                    )
                json.loads(gzip.decompress(body))
                bodies[page.page_id] = body
            with con.begin():
                lock_simulations(con, (page.simulation_id for page in batch))
                for page in batch:
                    # only if the backend did not store the page again since it was read
                    removed = con.execute(
                        db.delete(objects).where(objects.c.page_id == page.page_id, objects.c.key == page.key)
                    ).rowcount
                    if removed == 1:
                        con.execute(
                            db.update(pages)
                            .where(pages.c.id == page.page_id)
                            .values(compressed_data=bodies[page.page_id])
                        )
                        moved += 1
            click.echo(f"up to page {batch[-1].page_id}: {moved}/{total} back in the database")


if __name__ == "__main__":
    run()
