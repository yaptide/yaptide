from yaptide.persistence.database import db
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash


class UserModel(db.Model):
    """User model"""

    __tablename__ = 'User'
    id = db.Column(db.Integer, primary_key=True)
    login_name = db.Column(db.String, nullable=False)
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


def create_models():
    db.create_all()
