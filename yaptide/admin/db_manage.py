#! /usr/bin/env python
from enum import Enum, auto
import os

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class TableTypes(Enum):
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


def connect_to_db(verbose: int = 0):
    """Connects to the db"""
    db_uri = os.environ.get('FLASK_SQLALCHEMY_DATABASE_URI')
    click.echo(f'Found URI: {db_uri}')
    if not db_uri:
        click.echo(f'Database URI: {db_uri} not set - aborting', err=True)
        raise click.Abort()
    echo = False
    if verbose > 1:
        echo = True
    engine = db.create_engine(db_uri, echo=echo)
    try:
        con = engine.connect()
        metadata = db.MetaData()
        metadata.reflect(bind=engine)
    except db.exc.OperationalError:
        click.echo(f'Connection to db {db_uri} failed', err=True)
        raise click.Abort()
    return con, metadata, engine


def user_exists(name: str, auth_provider: str, users: db.Table, con) -> bool:
    """Check if user already exists"""

    # check if cluster already exists
    stmt = db.select(users).filter_by(username=name, auth_provider=auth_provider)
    users_found = con.execute(stmt).all()
    if len(users_found) > 0:
        click.echo(f'User: {name} exists')
        return True
    return False


@click.group()
def run():
    """Manage database"""


@run.command
def list_users():
    """List users"""
    con, _, _ = connect_to_db()
    stmt = db.select(db.column('username'), db.column('auth_provider')).select_from(db.table(TableTypes.User.name))
    users = con.execute(stmt).all()

    click.echo(f"{len(users)} users in DB:")
    for user in users:
        click.echo(f"Login {user.username}; Auth provider {user.auth_provider}")


@run.command
def list_tasks():
    """List tasks"""
    con, _, _ = connect_to_db()
    stmt = db.select(db.column('simulation_id'), db.column('task_id')).select_from(db.table(TableTypes.Task.name))
    tasks = con.execute(stmt).all()

    click.echo(f"{len(tasks)} tasks in DB:")
    for task in tasks:
        click.echo(f"Simulation id {task.simulation_id}; Task id ...{task.task_id}")


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('-v', '--verbose', count=True)
def add_user(name, password, verbose):
    """Add yaptide user to database"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f'Adding user: {name}')
    if verbose > 2:
        click.echo(f'Password: {password}')

    users = metadata.tables[TableTypes.User.name]

    if user_exists(name=name, auth_provider="YaptideUser", users=users, con=con):
        click.echo(f'YaptideUser: {name} already exists, aborting add')
        raise click.Abort()

    click.echo(f'YaptideUser: {name} does not exist, adding')
    click.echo(f'Adding user: {name}')
    query = db.insert(users).values(username=name, auth_provider="YaptideUser")
    result = con.execute(query)
    user_id = result.inserted_primary_key[0]
    password_hash = generate_password_hash(password)

    yaptide_users = metadata.tables[TableTypes.YaptideUser.name]
    query = db.insert(yaptide_users).values(id=user_id, password_hash=password_hash)
    con.execute(query)
    con.commit()


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('-v', '--verbose', count=True)
def update_user(**kwargs):
    """Update user in database"""
    con, metadata, engine = connect_to_db()
    username = kwargs['name']
    click.echo(f'Updating user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    yaptide_users = db.Table(TableTypes.YAPTIDEUSER.value, metadata, autoload=True, autoload_with=engine)

    if not user_exists(username, "YaptideUser", users, con):
        click.echo(f'YaptideUser: {username} does not exist, aborting update')
        return None

    # update password
    password = kwargs['password']
    if password:
        pwd_hash = generate_password_hash(password)

        subquery = db.select([users.c.id]).where(users.c.username == username,
                                                 users.c.auth_provider == "YaptideUser").scalar_subquery()

        query = db.update(yaptide_users).\
            where(yaptide_users.c.id == subquery).\
            values(password_hash=pwd_hash)
        con.execute(query)
        if kwargs['verbose'] > 2:
            click.echo(f'Updating password: {password}')
    click.echo(f'Successfully updated user: {username}')
    return None


@run.command
@click.argument('name')
@click.argument('auth_provider')
def remove_user(name, auth_provider):
    """Delete user"""
    con, metadata, _ = connect_to_db()
    click.echo(f'Deleting user: {name}')
    users = metadata.tables[TableTypes.User.name]

    # abort if user does not exist
    if not user_exists(name, auth_provider, users, con):
        click.echo(f"Aborting, user {name} does not exist")
        return None

    query = db.delete(users).where(users.c.username == name, users.c.auth_provider == auth_provider)
    con.execute(query)
    con.commit()
    click.echo(f'Successfully deleted user: {name}')
    return None


@run.command
def list_simulations():
    """List simulations"""
    con, _, _ = connect_to_db()
    stmt = db.select(db.column('id'), db.column('job_id'), db.column('start_time'),
                     db.column('end_time')).select_from(db.table(TableTypes.Simulation.name))
    sims = con.execute(stmt).all()

    click.echo(f"{len(sims)} simulations in DB:")
    for sim in sims:
        click.echo(f"id {sim.id}; job id {sim.job_id}; start_time {sim.start_time}; end_time {sim.end_time};")


@run.command
@click.argument('cluster_name')
@click.option('-v', '--verbose', count=True)
def add_cluster(cluster_name, verbose):
    """Adds cluster with provided name to database if it does not exist"""
    con, metadata, _ = connect_to_db()
    cluster_table = metadata.tables[TableTypes.Cluster.name]

    # check if cluster already exists
    stmt = db.select(cluster_table).filter_by(cluster_name=cluster_name)
    clusters = con.execute(stmt).all()
    if len(clusters) > 0:
        click.echo(f"Cluster {cluster_name} already exists in DB")
        return None

    stmt = db.insert(cluster_table).values(cluster_name=cluster_name)
    con.execute(stmt)
    con.commit()
    click.echo(f"Cluster {cluster_name} added to DB")


@run.command
def list_clusters(**kwargs):
    """List clusters"""
    con, metadata, engine = connect_to_db()
    stmt = db.select(metadata.tables[TableTypes.Cluster.name])
    clusters = con.execute(stmt).all()

    click.echo(f"{len(clusters)} clusters in DB:")
    for cluster in clusters:
        click.echo(f"id {cluster.id}; cluster name {cluster.cluster_name};")


if __name__ == "__main__":
    run()
