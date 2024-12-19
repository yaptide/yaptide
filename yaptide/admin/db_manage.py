#! /usr/bin/env python
"""
This script is used to manage the database via a command line application.
It is supposed to be used outside of the docker container, therefore by purpose it has
no dependency on the yaptide package. All the tables used by ORM are defined here again.
We do not use ORM model classes here, because we do not want to import the yaptide package.
"""
from enum import Enum, auto
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


def connect_to_db(verbose: int = 0) -> tuple[db.Connection, db.MetaData, db.Engine]:
    """Connects to the db"""
    db_uri = os.environ.get('FLASK_SQLALCHEMY_DATABASE_URI')
    if verbose > 1:
        click.echo(f'Connecting to URI: {db_uri}')
    if not db_uri:
        click.echo(f'Database URI: {db_uri} not set - aborting', err=True)
        raise click.Abort()
    echo: bool = verbose > 1
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
@click.option('-v', '--verbose', count=True)
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
def update_user(name, password, verbose):
    """Update user in database"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f'Updating user: {name}')
    users = metadata.tables[TableTypes.User.name]

    if not user_exists(name, "YaptideUser", users, con):
        click.echo(f'YaptideUser: {name} does not exist, aborting update')
        raise click.Abort()

    # update password
    if password:
        pwd_hash: str = generate_password_hash(password)
        yaptide_users = metadata.tables[TableTypes.YaptideUser.name]
        stmt = db.update(yaptide_users).\
            where(yaptide_users.c.id == users.c.id).\
            where(users.c.username == name).\
            where(users.c.auth_provider == "YaptideUser").\
            values(password_hash=pwd_hash)
        con.execute(stmt)
        con.commit()
        if verbose > 2:
            click.echo(f'Updating password: {password}')
    click.echo(f'Successfully updated user: {name}')


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
        raise click.Abort()

    query = db.delete(users).where(users.c.username == name, users.c.auth_provider == auth_provider)
    con.execute(query)
    con.commit()
    click.echo(f'Successfully deleted user: {name}')


@run.command
@click.option('sim_id', '--sim_id')
@click.option('user', '--user')
@click.option('auth_provider', '--auth-provider')
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
        filter_args_user['username'] = user
    if auth_provider:
        filter_args_user['auth_provider'] = auth_provider
    if sim_id:
        filter_args_simulation['simulation_id'] = int(sim_id)

    stmt = db.select(tasks.c.simulation_id, tasks.c.task_id, users.c.username, tasks.c.task_state
                     ).select_from(tasks).filter_by(**filter_args_simulation).join(
                         simulations, tasks.c.simulation_id == simulations.c.id).join(
                             users, simulations.c.user_id == users.c.id).filter_by(**filter_args_user).order_by(
                                 tasks.c.simulation_id, tasks.c.task_id)
    all_tasks = con.execute(stmt).all()

    click.echo(f"{len(all_tasks)} tasks in DB:")
    for task in all_tasks:
        simulation_id_col = f"Simulation id {task.simulation_id}"
        task_id_col = f"Task id ...{task.task_id}"
        task_state_col = f"task_state {task.task_state}"
        user_col = f" username {task.username}" if not user else ''

        click.echo('; '.join((simulation_id_col, task_id_col, task_state_col, user_col)))


@run.command
@click.argument('simulation_id')
@click.argument('task_id')
@click.option('-v', '--verbose', count=True)
def remove_task(simulation_id, task_id, verbose):
    """Delete task"""
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f'Deleting task: {task_id} from simulation: {simulation_id}')
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
    click.echo(f'Successfully deleted task: {task_id}')


@run.command
@click.option('-v', '--verbose', count=True)
@click.option('user', '--user')
@click.option('auth_provider', '--auth-provider')
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
        filter_args['username'] = user
    if auth_provider:
        filter_args['auth_provider'] = auth_provider

    stmt = db.select(simulations.c.id, simulations.c.job_id, simulations.c.start_time,
                     simulations.c.end_time, users.c.username).select_from(simulations).join(
                         users, simulations.c.user_id == users.c.id).filter_by(**filter_args)
    sims = con.execute(stmt).all()

    click.echo(f"{len(sims)} simulations in DB:")
    user_column = ''
    for sim in sims:
        user_column = f" username {sim.username}" if not user else ''
        click.echo(
            f"id {sim.id}; job id {sim.job_id}; start_time {sim.start_time}; end_time {sim.end_time};{user_column}")


@run.command
@click.argument('simulation_id')
@click.option('-v', '--verbose', count=True)
def remove_simulation(simulation_id, verbose):
    """Delete simulation"""
    simulation_id = int(simulation_id)
    con, metadata, _ = connect_to_db(verbose=verbose)
    click.echo(f'Deleting simulation: {simulation_id}')
    simulations = metadata.tables[TableTypes.Simulation.name]

    stmt = db.select(simulations).filter_by(id=simulation_id)
    simulation_found = con.execute(stmt).all()
    if not simulation_found:
        click.echo(f"Aborting, simulation {simulation_id} does not exist")
        raise click.Abort()

    query = db.delete(simulations).where(simulations.c.id == simulation_id)

    con.execute(query)
    con.commit()
    click.echo(f'Successfully deleted simulation: {simulation_id}')


@run.command
@click.argument('cluster_name')
@click.option('-v', '--verbose', count=True)
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


if __name__ == "__main__":
    run()
