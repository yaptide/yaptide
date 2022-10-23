import os

import json

from pathlib import Path
from enum import Enum

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


class DataUserFields(Enum):
    """Data JSON fields"""

    LOGIN = "LOGIN"
    PASSWORD = "PASSWORD"
    GRID_PROXY_NAME = "GRID_PROXY_NAME"


def select_all_simulations(con: db.engine.Connection, engine):
    """Selects all users from db"""
    metadata = db.MetaData()
    simulations = db.Table(TableTypes.SIMULATION.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([simulations])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(ResultSet)


def select_all_users(con: db.engine.Connection, engine):
    """Selects all users from db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(ResultSet)


def insert_user(con: db.engine.Connection, engine, data: dict):
    """Inserts new user to db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.insert(users).values(
        login_name=data[DataUserFields.LOGIN.value],
        password_hash=generate_password_hash(data[DataUserFields.PASSWORD.value])
    )
    try:
        con.execute(query)
        print(f'Successfully inserted user: {data[DataUserFields.LOGIN.value]}')
    except db.exc.IntegrityError:
        print(f'Inserting user: {data[DataUserFields.LOGIN.value]} failed, probably already exists')


def update_user(con: db.engine.Connection, engine, data: dict):
    """Updates user with provided login in db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    if DataUserFields.LOGIN.value not in data:
        print(f'{DataUserFields.LOGIN.value} not provided in UPDATE function')
        return
    if DataUserFields.PASSWORD.value in data:
        query = db.update(users).where(users.c.login_name == data[DataUserFields.LOGIN.value]).\
            values(password_hash=generate_password_hash(data[DataUserFields.PASSWORD.value]))
        con.execute(query)
    if DataUserFields.GRID_PROXY_NAME.value in data:
        grid_proxy_path = Path(os.path.dirname(os.path.realpath(__file__)), data[DataUserFields.GRID_PROXY_NAME.value])
        try:
            with open(grid_proxy_path) as grid_proxy_file:
                query = db.update(users).where(users.c.login_name == data[DataUserFields.LOGIN.value]).\
                    values(grid_proxy=grid_proxy_file.read())
                con.execute(query)
        except FileNotFoundError:
            print(f'Proxy file: {grid_proxy_path} does not exist - aborting update')
            return
    print(f'Successfully updated user: {data[DataUserFields.LOGIN.value]}')


def delete_user(con: db.engine.Connection, engine, data: dict):
    """Deletes user with provided login from db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.delete(users).where(users.c.login_name == data[DataUserFields.LOGIN.value])
    con.execute(query)
    print(f'Successfully deleted user: {data[DataUserFields.LOGIN.value]}')


if __name__ == "__main__":

    OPERATION = "OPERATION"
    TABLE = "TABLE"
    DATA = "DATA"

    file_dir = os.path.dirname(os.path.realpath(__file__))
    input_json_path = Path(file_dir, 'script_input.json')
    with open(input_json_path) as json_file:
        json_data = json.load(json_file)
    db_engine = db.create_engine(f'sqlite:////{file_dir}/main.db')
    connection = db_engine.connect()

    for obj in json_data:
        if OPERATION not in obj:
            raise ValueError(f'No OPERATION field in provided JSON object: {obj}')
        if TABLE not in obj:
            raise ValueError(f'No TABLE field in provided JSON object: {obj}')
        if DATA not in obj:
            raise ValueError(f'No DATA field in provided JSON object: {obj}')

        if obj[OPERATION] == OperationTypes.INSERT.value and obj[TABLE] == TableTypes.USER.value:
            insert_user(con=connection, engine=db_engine, data=obj[DATA])
        if obj[OPERATION] == OperationTypes.UPDATE.value and obj[TABLE] == TableTypes.USER.value:
            update_user(con=connection, engine=db_engine, data=obj[DATA])
        if obj[OPERATION] == OperationTypes.DELETE.value and obj[TABLE] == TableTypes.USER.value:
            delete_user(con=connection, engine=db_engine, data=obj[DATA])
        if obj[OPERATION] == OperationTypes.SELECT.value:
            if obj[TABLE] == TableTypes.USER.value:
                select_all_users(con=connection, engine=db_engine)
            else:
                select_all_simulations(con=connection, engine=db_engine)
