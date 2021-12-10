from flask_restful import Resource

from yaptide.routes.simulation_routes import SimulationRun, SimulationStatus, SimulationInputs, SimulationCancel
from yaptide.routes.user_routes import UserSimulations
from yaptide.routes.auth_routes import AuthRegister, AuthLogIn, AuthRefresh, AuthStatus, AuthLogOut


class HelloWorld(Resource):
    def get(self):
        return {'message': 'Hello world!'}


def initialize_routes(api):
    api.add_resource(HelloWorld, "/")

    api.add_resource(SimulationRun, "/sh/run")
    api.add_resource(SimulationStatus, "/sh/status")
    api.add_resource(SimulationInputs, "/sh/inputs")
    api.add_resource(SimulationCancel, "/sh/cancel")

    api.add_resource(UserSimulations, "/user/simulations")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")
