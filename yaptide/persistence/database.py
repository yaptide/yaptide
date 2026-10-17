import logging
import sqlite3
import time
from typing import Callable

import psycopg
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Engine, event, make_url
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models"""


db = SQLAlchemy(model_class=Base)


@event.listens_for(Engine, "connect")
def enforce_sqlite_foreign_keys(dbapi_connection, _):
    """SQLite ignores foreign keys unless asked, and deletes rely on them cascading (as on Postgres)"""
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def listen_to(database_uri: str, channel: str, connected: Callable[[], None], notified: Callable[[str], None]) -> None:
    """Calls notified with the payload of every notification on the channel, connecting again whenever the connection
    is lost; connected is called after every (re)connection, to catch up with what came while nobody listened
    """
    if make_url(database_uri).get_backend_name() != "postgresql":
        # SQLite has no notifications (local development only)
        while True:
            connected()
            time.sleep(2)
    conninfo = make_url(database_uri).set(drivername="postgresql").render_as_string(hide_password=False)
    while True:
        try:
            # keepalives notice a connection that died silently, so nobody waits on it forever
            with psycopg.connect(
                conninfo, autocommit=True, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3
            ) as connection:
                connection.execute(f"LISTEN {channel}")
                connected()
                for notify in connection.notifies():
                    notified(notify.payload)
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Listening on %s failed, connecting again", channel)
            time.sleep(1)
