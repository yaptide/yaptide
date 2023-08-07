from flask_restful import Api, Resource

from yaptide.routes.auth_routes import AuthLogIn, AuthLogOut, AuthRefresh, AuthRegister, AuthStatus
from yaptide.routes.batch_routes import Clusters, JobsBatch
from yaptide.routes.celery_routes import ConvertInputFiles, JobsDirect
from yaptide.routes.common_sim_routes import SimulationInputs, SimulationLogfiles, SimulationResults
from yaptide.routes.keycloak_routes import AuthKeycloak
from yaptide.routes.task_routes import TaskUpdate
from yaptide.routes.user_routes import UserSimulations, UserUpdate


class HelloWorld(Resource):
    """Root route"""

    @staticmethod
    def get():
        """Root route get method"""
        return {'message': 'Hello world!'}


def initialize_routes(api: Api):
    """Function initializing routes"""
    api.add_resource(HelloWorld, "/")

    api.add_resource(JobsDirect, "/jobs/direct")
    api.add_resource(JobsBatch, "/jobs/batch")

    api.add_resource(TaskUpdate, "/tasks")

    api.add_resource(SimulationResults, "/results")
    api.add_resource(SimulationInputs, "/inputs")
    api.add_resource(SimulationLogfiles, "/logfiles")

    api.add_resource(ConvertInputFiles, "/convert")

    api.add_resource(UserSimulations, "/user/simulations")
    api.add_resource(UserUpdate, "/user/update")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")

    api.add_resource(AuthKeycloak, "/auth/keycloak")

    api.add_resource(Clusters, "/clusters")
