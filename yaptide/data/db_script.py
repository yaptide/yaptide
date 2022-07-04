import os

import json

from pathlib import Path

import sqlalchemy as db
from werkzeug.security import generate_password_hash


def select_all_users(connection):
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = connection.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(ResultSet)


def add_user(connection, data: dict):
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.insert(users).values(
        login_name=data["LOGIN"],
        password_hash=generate_password_hash(data["PASSWORD"])
    )
    connection.execute(query)


def delete_user(connection, data: dict):
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.delete(users).where(
       users.c.login_name == data["LOGIN"]
    )
    connection.execute(query)


def update_user(connection, data: dict):
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.update(users).where(
       users.c.login_name == data["LOGIN"]
    ).values(
        password_hash=generate_password_hash(data["PASSWORD"])
    )
    connection.execute(query)


if __name__ == "__main__":
    input_json_path = Path(os.path.dirname(os.path.realpath(__file__)), 'script_input.json')
    with open(input_json_path) as json_file:
        json_data = json.load(json_file)
    engine = db.create_engine('sqlite:///main.db')
    connection = engine.connect()

    for obj in json_data:
        if obj["OPERATION"] == "INSERT":
            if obj["TABLE"] == "User":
                add_user(connection=connection, data=obj["DATA"])
        if obj["OPERATION"] == "UPDATE":
            if obj["TABLE"] == "User":
                update_user(connection=connection, data=obj["DATA"])
        if obj["OPERATION"] == "DELETE":
            if obj["TABLE"] == "User":
                delete_user(connection=connection, data=obj["DATA"])
        select_all_users(connection=connection)
