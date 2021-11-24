from yaptide.persistence.database import db
from werkzeug.security import generate_password_hash, check_password_hash


class UserModel(db.Model):
    """User model"""

    id = db.Column(db.Integer, primary_key=True)
    login_name = db.Column(db.String, nullable=False)
    password_hash = db.Column(db.String, nullable=False)

    def set_password(self, password):
        """Sets hashed password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password) -> bool:
        """Checks password correctness"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f'User #{self.id} {self.login_name}'


def create_models():
    db.create_all()
