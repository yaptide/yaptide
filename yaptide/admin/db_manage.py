from enum import Enum
from pathlib import Path
import hashlib

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class TableTypes(Enum):
    """Table types"""

    USER = "User"
    SIMULATION = "Simulation"


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


def user_exists(name: str, users: db.Table, con) -> bool:
    """Check if user already exists"""
    query = db.select([users]).where(users.c.login_name == name)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        click.echo(f'User: {name} already exists')
        return True
    return False


def proxy_hash(proxy_content: str) -> str:
    """User friendly proxy hash"""
    last_part_of_hash = 'None'
    if proxy_content is not None:
        h = hashlib.sha256()
        h.update(proxy_content.encode('utf-8'))
        last_part_of_hash = '...' + h.hexdigest()[-10:]
    return last_part_of_hash


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
        click.echo(f"Login {row.login_name} ; Passw ...{row.password_hash[-10:]} ; Proxy {proxy_hash(row.grid_proxy)}")
    return None


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('proxy', '--proxy', type=click.File(mode='r'))
@click.option('-v', '--verbose', count=True)
def add_user(**kwargs):
    """Add user to database"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    password = kwargs['password']
    proxy_file_handle = kwargs['proxy']
    proxy_content = None
    if proxy_file_handle is not None:
        proxy_content = proxy_file_handle.read()
    click.echo(f'Adding user: {username}')
    if kwargs['verbose'] > 2:
        click.echo(f'Password: {password}')
    if kwargs['verbose'] > 1:
        click.echo(f'Proxy: {proxy_hash(proxy_content)}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    if user_exists(username, users, con):
        return None

    query = db.insert(users).values(login_name=username,
                                    password_hash=generate_password_hash(password),
                                    grid_proxy=proxy_content)
    con.execute(query)
    return None


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('proxy', '--proxy', type=click.File(mode='r'))
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

    # update proxy
    proxy_file_handle = kwargs['proxy']
    proxy_content = None
    if proxy_file_handle is not None:
        proxy_content = proxy_file_handle.read()
        query = db.update(users).where(users.c.login_name == username).values(grid_proxy=proxy_content)
        if kwargs['verbose'] > 1:
            click.echo(f'Updating proxy: {proxy_hash(proxy_content)}')
        con.execute(query)

    # update password
    password = kwargs['password']
    if password:
        pwd_hash = generate_password_hash(password)
        query = db.update(users).where(users.c.login_name == username).values(password_hash=pwd_hash)
        con.execute(query)
        if kwargs['verbose'] > 2:
            click.echo(f'Updating password: {password}')
    click.echo(f'Successfully updated user: {username}')
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

    query = db.delete(users).where(users.c.login_name == username)
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
        click.echo(f"id {row.id} ; task id {row.task_id} ; start_time {row.start_time}; end_time {row.end_time};")
    return None


if __name__ == "__main__":
    run()
