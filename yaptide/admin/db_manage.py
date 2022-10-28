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
        print(f'Database file: {sqlite_file_path} does not exist - aborting')
        return None, None, None
    engine = db.create_engine(f'sqlite:////{sqlite_file_path}')
    try:
        con = engine.connect()
        metadata = db.MetaData()
    except db.exc.OperationalError:
        print(f'Connection to db {sqlite_file_path} failed')
        return None, None, None
    return con, metadata, engine


def user_exists(name: str, users: db.Table, con) -> bool:
    """Check if user already exists"""
    query = db.select([users]).where(users.c.login_name == name)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        print(f'User: {name} already exists')
        return True
    return False


@click.group()
def run():
    """Manage database"""


@run.command
def list_users():
    """List all users"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(f"{len(ResultSet)} users in DB:")
    for row in ResultSet:
        last_part_of_hash = 'None'
        if row.grid_proxy is not None:
            h = hashlib.sha256()
            h.update(row.grid_proxy.encode('utf-8'))
            last_part_of_hash = '...' + h.hexdigest()[-10:]
        print(f"Login {row.login_name} ; Password hash ...{row.password_hash[-10:]} ; Proxy {last_part_of_hash}")
    return None


@run.command
@click.argument('name')
@click.option('password', '--password', default='')
@click.option('proxy', '--proxy', type=click.File(mode='r'))
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
    print(f'Adding user: {username}')
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
def update_user(**kwargs):
    """Update user in database"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    print(f'Updating user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    if user_exists(username, users, con):
        return None

    password = kwargs['password']
    proxy_file_handle = kwargs['proxy']
    proxy_content = None
    if proxy_file_handle is not None:
        proxy_content = proxy_file_handle.read()

    # update password and proxy if provided:
    query = db.update(users).where(users.c.login_name == username).\
        values(password_hash=generate_password_hash(password), grid_proxy=proxy_content)
    con.execute(query)
    print(f'Successfully updated user: {username}')
    return None


@run.command
@click.argument('name')
def remove_user(**kwargs):
    """Deletes user with provided login from db"""
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    print(f'Deleting user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    # abort if user does not exist
    if not user_exists(username, users, con):
        print("Aborting, user does not exist")
        return None

    query = db.delete(users).where(users.c.login_name == username)
    con.execute(query)
    print(f'Successfully deleted user: {username}')
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
    print(f"{len(ResultSet)} simulations in DB:")
    for row in ResultSet:
        print(f"id {row.id} ; task id {row.task_id} ; start_time {row.start_time}; end_time {row.end_time};")
    return None


if __name__ == "__main__":
    run()
