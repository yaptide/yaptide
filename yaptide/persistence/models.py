from yaptide.persistence.database import db
from werkzeug.security import generate_password_hash, check_password_hash

############### Example user ###############
# (this is an example model, demonstration pourpose only)


class UserModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    token_hash = db.Column(db.String, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_token(self, token):
        self.token_hash = generate_password_hash(token)

    def check_token(self, token):
        return check_password_hash(self.token_hash, token)

    def __repr__(self) -> str:
        return f'User #{self.id} {self.email}'


############################################

def create_models():
    db.create_all()
