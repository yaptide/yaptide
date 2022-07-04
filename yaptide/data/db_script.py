import os

import json

from pathlib import Path

import sqlalchemy as db
from werkzeug.security import generate_password_hash


def select_all_users(con: db.engine.Connection):
    """Selects all users from db"""
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.select([users])
    ResultProxy = con.execute(query)
    ResultSet = ResultProxy.fetchall()
    print(ResultSet)


def insert_user(con: db.engine.Connection, data: dict):
    """Inserts new user to db"""
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.insert(users).values(
        login_name=data["LOGIN"],
        password_hash=generate_password_hash(data["PASSWORD"])
    )
    con.execute(query)


def update_user(con: db.engine.Connection, data: dict):
    """Updates user with provided login in db"""
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.update(users).where(
       users.c.login_name == data["LOGIN"]
    ).values(
        password_hash=generate_password_hash(data["PASSWORD"])
    )
    con.execute(query)


def delete_user(con: db.engine.Connection, data: dict):
    """Deletes user with provided login from db"""
    metadata = db.MetaData()
    users = db.Table('User', metadata, autoload=True, autoload_with=engine)
    query = db.delete(users).where(
       users.c.login_name == data["LOGIN"]
    )
    con.execute(query)


if __name__ == "__main__":
    input_json_path = Path(os.path.dirname(os.path.realpath(__file__)), 'script_input.json')
    with open(input_json_path) as json_file:
        json_data = json.load(json_file)
    engine = db.create_engine('sqlite:///main.db')
    connection = engine.connect()

    for obj in json_data:
        if obj["OPERATION"] == "INSERT" and obj["TABLE"] == "User":
            insert_user(con=connection, data=obj["DATA"])
        if obj["OPERATION"] == "UPDATE" and obj["TABLE"] == "User":
            update_user(con=connection, data=obj["DATA"])
        if obj["OPERATION"] == "DELETE" and obj["TABLE"] == "User":
            delete_user(con=connection, data=obj["DATA"])
        select_all_users(con=connection)
