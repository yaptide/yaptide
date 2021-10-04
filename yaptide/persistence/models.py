from yaptide.persistence.database import db

############### Example user ###############
# (this is an example model, demonstration pourpose only)


class ExampleUserModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)

    def __repr__(self) -> str:
        return f'User #{self.id} {self.name}'


############################################

def create_models():
    db.create_all()
