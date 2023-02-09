from flask_restful import Resource

from yaptide.routes.simulation_routes import (SimulationRun, SimulationStatus, SimulationInputs,
                                              SimulationCancel, ConvertInputFiles)
from yaptide.routes.user_routes import UserSimulations, UserUpdate
from yaptide.routes.auth_routes import AuthRegister, AuthLogIn, AuthRefresh, AuthStatus, AuthLogOut

from plgrid.plgrid_routes import RimrockJobs, PlgData

from slurm.slurm_routes import SlurmJobs, SlurmData


class HelloWorld(Resource):
    """Root route"""

    @staticmethod
    def get():
        """Root route get method"""
        return {'message': 'Hello world!'}


def initialize_routes(api):
    """Function initializing routes"""
    api.add_resource(HelloWorld, "/")

    api.add_resource(SimulationRun, "/sh/run")
    api.add_resource(ConvertInputFiles, "/sh/convert")
    api.add_resource(SimulationStatus, "/sh/status")
    api.add_resource(SimulationInputs, "/sh/inputs")
    api.add_resource(SimulationCancel, "/sh/cancel")

    api.add_resource(UserSimulations, "/user/simulations")
    api.add_resource(UserUpdate, "/user/update")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")

    api.add_resource(RimrockJobs, "/plgrid/jobs")
    api.add_resource(PlgData, "/plgrid/data")

    api.add_resource(SlurmJobs, "/slurm/jobs")
    api.add_resource(SlurmData, "/slurm/data")
