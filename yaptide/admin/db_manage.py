from enum import Enum
from pathlib import Path

import click
import sqlalchemy as db
from werkzeug.security import generate_password_hash


class OperationTypes(Enum):
    """Operation types"""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SELECT = "SELECT"


class TableTypes(Enum):
    """Table types"""

    USER = "User"
    SIMULATION = "Simulation"


# def update_user(con: db.engine.Connection, metadata: db.MetaData, engine, data: dict):
#     """Updates user with provided login in db"""
#     users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
#     if DataUserFields.LOGIN.value not in data:
#         print(f'{DataUserFields.LOGIN.value} not provided in UPDATE function')
#         return
#     if DataUserFields.PASSWORD.value in data:
#         query = db.update(users).where(users.c.login_name == data[DataUserFields.LOGIN.value]).\
#             values(password_hash=generate_password_hash(data[DataUserFields.PASSWORD.value]))
#         con.execute(query)
#     if DataUserFields.GRID_PROXY_NAME.value in data:
#         grid_proxy_path = Path(os.path.dirname(os.path.realpath(__file__)), data[DataUserFields.GRID_PROXY_NAME.value])
#         try:
#             with open(grid_proxy_path) as grid_proxy_file:
#                 query = db.update(users).where(users.c.login_name == data[DataUserFields.LOGIN.value]).\
#                     values(grid_proxy=grid_proxy_file.read())
#                 con.execute(query)
#         except FileNotFoundError:
#             print(f'Proxy file: {grid_proxy_path} does not exist - aborting update')
#             return
#     print(f'Successfully updated user: {data[DataUserFields.LOGIN.value]}')


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

@click.group()
def run():
    pass

@run.command
def list_users():
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(f"{len(ResultSet)} users in DB:")
    for row in ResultSet:
        print(f"Login {row['login_name']} ; Password hash {row['password_hash']} ; Proxy {row['grid_proxy']}")

@run.command
@click.argument('name')
@click.option('password', '--password', default='')
def add_user(**kwargs):
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    password = kwargs['password']
    print(f'Adding user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    # check if user already exists
    query = db.select([users]).where(users.c.login_name == username)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) > 0:
        print(f'User: {username} already exists')
        return None

    query = db.insert(users).values(
        login_name=username,
        password_hash=generate_password_hash(password)
    )
    con.execute(query)

@run.command
@click.argument('name')
@click.option('password', '--password', default='')
def update_user(**kwargs):
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    username = kwargs['name']
    password = kwargs['password']
    print(f'Updating user: {username}')
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)

    # check if user exists:
    query = db.select([users]).where(users.c.login_name == username)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) == 0:
        print(f'User: {username} does not exist - aborting update')
        return

    # update password if provided:
    query = db.update(users).where(users.c.login_name == username).\
        values(password_hash=generate_password_hash(password))
    con.execute(query)
    print(f'Successfully updated user: {username}')

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

    # check if user exists:
    query = db.select([users]).where(users.c.login_name == username)
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    if len(ResultSet) == 0:
        print(f'User: {username} does not exist - aborting delete')
        return

    query = db.delete(users).where(users.c.login_name == username)
    con.execute(query)
    print(f'Successfully deleted user: {username}')

@run.command
def list_simulations(**kwargs):
    con, metadata, engine = connect_to_db()
    if con is None or metadata is None or engine is None:
        return None
    simulations = db.Table(TableTypes.SIMULATION.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([simulations])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(f"{len(ResultSet)} simulations in DB:")
    for row in ResultSet:
        print(f"Id {row['id']} ; Name {row['name']} ; Status {row['status']} ; User {row['user_id']}")

if __name__ == "__main__":
    run()
