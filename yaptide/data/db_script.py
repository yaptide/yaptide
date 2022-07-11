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


class TableTypes(Enum):
    """Table types"""

    USER = "User"


class DataJsonFields(Enum):
    """Data JSON fields"""

    LOGIN = "LOGIN"
    PASSWORD = "PASSWORD"


def select_all_users(con: db.engine.Connection):
    """Selects all users from db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(ResultSet)


def insert_user(con: db.engine.Connection, data: dict):
    """Inserts new user to db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.insert(users).values(
        login_name=data[DataJsonFields.LOGIN.value],
        password_hash=generate_password_hash(data[DataJsonFields.PASSWORD.value])
    )
    con.execute(query)
    print(f'Successfully inserted user: {data[DataJsonFields.LOGIN.value]}')


def update_user(con: db.engine.Connection, data: dict):
    """Updates user with provided login in db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.update(users).where(
       users.c.login_name == data[DataJsonFields.LOGIN.value]
    ).values(
        password_hash=generate_password_hash(data[DataJsonFields.PASSWORD.value])
    )
    con.execute(query)
    print(f'Successfully updated user: {data[DataJsonFields.LOGIN.value]}')


def delete_user(con: db.engine.Connection, data: dict):
    """Deletes user with provided login from db"""
    metadata = db.MetaData()
    users = db.Table(TableTypes.USER.value, metadata, autoload=True, autoload_with=engine)
    query = db.delete(users).where(
       users.c.login_name == data[DataJsonFields.LOGIN.value]
    )
    con.execute(query)
    print(f'Successfully deleted user: {data[DataJsonFields.LOGIN.value]}')


if __name__ == "__main__":

    OPERATION = "OPERATION"
    TABLE = "TABLE"
    DATA = "DATA"

    file_dir = os.path.dirname(os.path.realpath(__file__))
    input_json_path = Path(file_dir, 'script_input.json')
    with open(input_json_path) as json_file:
        json_data = json.load(json_file)
    engine = db.create_engine(f'sqlite:////{file_dir}/main.db')
    connection = engine.connect()

    for obj in json_data:
        if OPERATION not in obj:
            raise ValueError(f'No OPERATION field in provided JSON object: {obj}')
        if TABLE not in obj:
            raise ValueError(f'No TABLE field in provided JSON object: {obj}')
        if DATA not in obj:
            raise ValueError(f'No DATA field in provided JSON object: {obj}')

        if obj[OPERATION] == OperationTypes.INSERT.value and obj[TABLE] == TableTypes.USER.value:
            insert_user(con=connection, data=obj[DATA])
        if obj[OPERATION] == OperationTypes.UPDATE.value and obj[TABLE] == TableTypes.USER.value:
            update_user(con=connection, data=obj[DATA])
        if obj[OPERATION] == OperationTypes.DELETE.value and obj[TABLE] == TableTypes.USER.value:
            delete_user(con=connection, data=obj[DATA])
