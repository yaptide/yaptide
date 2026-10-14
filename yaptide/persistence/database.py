import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Engine, event
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models"""


db = SQLAlchemy(model_class=Base)


@event.listens_for(Engine, "connect")
def enforce_sqlite_foreign_keys(dbapi_connection, _):
    """SQLite ignores foreign keys unless asked, and deletes rely on them cascading (as on Postgres)"""
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
