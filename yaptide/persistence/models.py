from yaptide.persistence.database import db
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import jwt

_Test_secret_key = "secret_key"


class UserModel(db.Model):
    """User model"""

    id = db.Column(db.Integer, primary_key=True)
    login_name = db.Column(db.String, nullable=False)
    password_hash = db.Column(db.String, nullable=False)

    def set_password(self, password):
        """Sets hashed password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks password correctness"""
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def encode_auth_token(user_id):
        """
        Generates the Auth Token
        :return: string
        """
        try:
            payload = {
                'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=1800),
                'iat': datetime.datetime.utcnow(),
                'sub': user_id
            }
            return jwt.encode(
                payload,
                _Test_secret_key,
                algorithm='HS256'
            )
        except Exception as e:  # skipcq: PYL-W0703
            return e

    @staticmethod
    def decode_auth_token(token):
        """
        Decodes the auth token
        :param token:
        :return: integer|string
        """
        try:
            payload = jwt.decode(token, _Test_secret_key, algorithms=['HS256'])
            return payload['sub']
        except jwt.ExpiredSignatureError:
            return 'Signature expired. Please log in again.'
        except jwt.InvalidTokenError:
            return 'Invalid token. Please log in again.'

    def __repr__(self) -> str:
        return f'User #{self.id} {self.login_name}'


def create_models():
    db.create_all()
