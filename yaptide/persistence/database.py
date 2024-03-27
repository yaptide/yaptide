from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models"""


db = SQLAlchemy(model_class=Base)
