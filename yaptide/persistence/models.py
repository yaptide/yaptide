from yaptide.persistence.database import db
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import jwt

############### Example user ###############
# (this is an example model, demonstration pourpose only)
_Test_secret_key = "secret_key"

class UserModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login_name = db.Column(db.String, nullable=False)
    password_hash = db.Column(db.String, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def encode_auth_token(self, user_id):
        """
        Generates the Auth Token
        :return: string
        """
        try:
            payload = {
                'exp': datetime.datetime.utcnow() + datetime.timedelta(days=0, seconds=5),
                'iat': datetime.datetime.utcnow(),
                'sub': user_id
            }
            return jwt.encode(
                payload,
                _Test_secret_key,
                algorithm='HS256'
            )
        except Exception as e:
            return e

    @staticmethod
    def decode_auth_token(auth_token):
        """
        Decodes the auth token
        :param auth_token:
        :return: integer|string
        """
        try:
            payload = jwt.decode(auth_token, _Test_secret_key)
            return payload['sub']
        except jwt.ExpiredSignatureError:
            return 'Signature expired. Please log in again.'
        except jwt.InvalidTokenError:
            return 'Invalid token. Please log in again.'
                
    def __repr__(self) -> str:
        return f'User #{self.id} {self.login_name}'


############################################

def create_models():
    db.create_all()
