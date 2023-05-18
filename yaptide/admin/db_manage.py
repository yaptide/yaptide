from enum import Enum
from pathlib import Path

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class TableTypes(Enum):
    """Table types"""

    USER = "User"
    SIMULATION = "Simulation"
    CLUSTER = "Cluster"
    TASK = "Task"
    RESULT = "Result"


def connect_to_db():
    """Connects to db"""
    # sqlite_file_path = Path(Path(__file__).resolve().parent.parent, 'data', 'main.db')
    sqlite_file_path = Path('/main.db')
    if not sqlite_file_path.exists():
        click.echo(f'Database file: {sqlite_file_path} does not exist - aborting', err=True)
        return None, None, None
    engine = db.create_engine(f'sqlite:////{sqlite_file_path}')
    try:
        con = engine.connect()
        metadata = db.MetaData()
    except db.exc.OperationalError:
        click.echo(f'Connection to db {sqlite_file_path} failed', err=True)
        return None, None, None
    return con, metadata, engine


def user_exists(name: str, users: db.Table, con) -> bool:
    """Check if user already exists"""
    query = db.select([users]).where(users.c.username == name)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        click.echo(f'User: {name} already exists')
        return True
    return False


@click.group()
def run():
    """Manage database"""


@run.command
def list_users(**kwargs):
    """List all users"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} users in DB:")
    for row in ResultSet:
        click.echo(f"Login {row.username}; Passw ...{row.password_hash[-10:]}")
    return None


@run.command
def list_tasks(**kwargs):
    """List all tasks"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    tasks = db.Table(TableTypes.TASK.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([tasks])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} tasks in DB:")
    for row in ResultSet:
        click.echo(f"Simulation id {row.simulation_id}; Task id ...{row.task_id}")
    return None


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('-v', '--verbose', count=True)
def add_user(**kwargs):
    """Add user to database"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    password = kwargs['password']
    click.echo(f'Adding user: {username}')
    if kwargs['verbose'] > 2:
        click.echo(f'Password: {password}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    if user_exists(username, users, con):
        return None

    query = db.insert(users).values(username=username,
                                    password_hash=generate_password_hash(password))
    con.execute(query)
    return None


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('-v', '--verbose', count=True)
def update_user(**kwargs):
    """Update user in database"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    click.echo(f'Updating user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    if not user_exists(username, users, con):
        click.echo(f'User: {username} does not exist, aborting update')
        return None

    # update password
    password = kwargs['password']
    if password:
        pwd_hash = generate_password_hash(password)
        query = db.update(users).\
            where(users.c.username == username).\
            values(password_hash=pwd_hash)
        con.execute(query)
        if kwargs['verbose'] > 2:
            click.echo(f'Updating password: {password}')
    click.echo(f'Successfully updated user: {username}')
    return None


@run.command
@click.argument('username')
@click.argument('cluster_name')
@click.argument('cluster_username')
@click.argument('ssh_key', type=click.File(mode='r'))
@click.option('-v', '--verbose', count=True)
def add_ssh_key(**kwargs):
    """Adds ssh key to allow the user to connect to cluster"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['username']
    cluster_name = kwargs['cluster_name']
    cluster_username = kwargs['cluster_username']
    ssh_key = kwargs['ssh_key']
    ssh_key_content = ssh_key.read()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    clusters = db.Table(TableTypes.CLUSTER.value, metadata, autoload=True, autoload_with=engine)

    query = db.select([users]).where(users.c.username == username)
    ResultProxy = con.execute(query)
    user = ResultProxy.first()

    if not user:
        click.echo(f'User: {username} does not exist, aborting adding ssh key')
        return None

    query = db.select([clusters]).\
        where((clusters.c.user_id == user.id) & (clusters.c.cluster_name == cluster_name))
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        click.echo(f'User: {username} already has key and username for cluster: {cluster_name} - updating old one')
        query = db.update(clusters).\
            where((clusters.c.user_id == user.id) & (clusters.c.cluster_name == cluster_name)).\
            values(cluster_username=cluster_username, cluster_ssh_key=ssh_key_content)
    else:
        click.echo(f'Adding key and username for user: {username}, for cluster: {cluster_name}')
        query = db.insert(clusters).values(user_id=user.id,
                                           cluster_name=cluster_name,
                                           cluster_username=cluster_username,
                                           cluster_ssh_key=ssh_key_content)
    con.execute(query)
    return None


@run.command
@click.argument('name')
def remove_user(**kwargs):
    """Deletes user with provided login from db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    click.echo(f'Deleting user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    # abort if user does not exist
    if not user_exists(username, users, con):
        click.echo("Aborting, user does not exist")
        return None

    query = db.delete(users).where(users.c.username == username)
    con.execute(query)
    click.echo(f'Successfully deleted user: {username}')
    return None


@run.command
def list_simulations(**kwargs):
    """List all simulations in db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    simulations = db.Table(TableTypes.SIMULATION.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([simulations])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} simulations in DB:")
    for row in ResultSet:
        click.echo(f"id {row.id}; job id {row.job_id}; start_time {row.start_time}; end_time {row.end_time};")
    return None


@run.command
def list_clusters(**kwargs):
    """List all simulations in db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    clusters = db.Table(TableTypes.CLUSTER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([clusters])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} simulations in DB:")
    for row in ResultSet:
        click.echo(f"id {row.id}; user id {row.user_id}; cluster name {row.cluster_name};")
    return None


if __name__ == "__main__":
    run()
