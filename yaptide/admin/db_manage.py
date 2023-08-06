from enum import Enum
from pathlib import Path

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class TableTypes(Enum):
    """Table types"""

    USER = "User"
    YAPTIDEUSER = "YaptideUser"
    KEYCLOAKUSER = "KeycloakUser"
    SIMULATION = "Simulation"
    CLUSTER = "Cluster"
    TASK = "Task"
    RESULT = "Result"


def connect_to_db():
    """Connects to db"""
    sqlite_file_path = Path(Path(__file__).resolve().parent.parent, 'data', 'main.db')
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


def user_exists(name: str, auth_provider: str, users: db.Table, con) -> bool:
    """Check if user already exists"""
    query = db.select(users).where(users.c.username == name, users.c.auth_provider == auth_provider)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        click.echo(f'User: {name} exists')
        return True
    return False


@click.group()
def run():
    """Manage database"""


@run.command
def list_users(**kwargs):
    """List users"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} users in DB:")
    for row in ResultSet:
        click.echo(f"Login {row.username}; Auth provider {row.auth_provider}")
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
    """Add yaptide user to database"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    password = kwargs['password']
    click.echo(f'Adding user: {username}')
    if kwargs['verbose'] > 2:
        click.echo(f'Password: {password}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    yaptide_users = db.Table(TableTypes.YAPTIDEUSER.value, metadata, autoload=True, autoload_with=engine)

    if user_exists(username, "YaptideUser", users, con):
        return None
    query = db.insert(users).values(username=username, auth_provider="YaptideUser")
    result = con.execute(query)
    user_id = result.inserted_primary_key[0]
    password_hash = generate_password_hash(password)

    query = db.insert(yaptide_users).values(id=user_id, password_hash=password_hash)
    result = con.execute(query)

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
@click.argument('cluster_name')
@click.option('-v', '--verbose', count=True)
def add_cluster(**kwargs):
    """Adds ssh key to allow the user to connect to cluster"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    cluster_name = kwargs['cluster_name']

    clusters = db.Table(TableTypes.CLUSTER.value, metadata, autoload=True, autoload_with=engine)

    query = db.select([clusters]).where(clusters.c.cluster_name == cluster_name)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        click.echo(f'Cluster: {cluster_name} already exists, aborting adding cluster')
        return None

    click.echo(f'Adding cluster: {cluster_name}')
    query = db.insert(clusters).values(cluster_name=cluster_name)
    con.execute(query)
    return None


@run.command
@click.argument('name')
@click.argument('auth_provider')
def remove_user(**kwargs):
    """Deletes user with provided login from db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    auth_provider = kwargs['auth_provider']
    click.echo(f'Deleting user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    # abort if user does not exist
    if not user_exists(username, auth_provider, users, con):
        click.echo("Aborting, user does not exist")
        return None

    query = db.delete(users).where(users.c.username == username, users.c.auth_provider == auth_provider)
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
    """List all clusters in db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    clusters = db.Table(TableTypes.CLUSTER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([clusters])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    click.echo(f"{len(ResultSet)} clusters in DB:")
    for row in ResultSet:
        click.echo(f"id {row.id}; cluster name {row.cluster_name};")
    return None


if __name__ == "__main__":
    run()
