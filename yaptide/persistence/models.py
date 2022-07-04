from yaptide.persistence.database import db
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash, check_password_hash


class UserModel(db.Model):
    """User model"""

    __tablename__ = 'User'
    id = db.Column(db.Integer, primary_key=True)
    login_name = db.Column(db.String, nullable=False, unique=True)
    password_hash = db.Column(db.String, nullable=False)
    simulations = relationship("SimulationModel")

    def set_password(self, password: str):
        """Sets hashed password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Checks password correctness"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f'User #{self.id} {self.login_name}'


class SimulationModel(db.Model):
    """Simulation model - initial version"""

    __tablename__ = 'Simulation'
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('User.id'))
    creation_date = db.Column(db.DateTime(timezone=True), default=func.now())
    name = db.Column(db.String, nullable=False, default='workspace')


def add_user(login_name: str, password: str):
    """Function adding user"""
    user = UserModel(login_name=login_name)
    user.set_password(password)

    db.session.add(user)
    db.session.commit()


def create_models():
    """Function creating database's models"""
    db.create_all()
