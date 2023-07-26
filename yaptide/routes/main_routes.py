from flask_restful import Resource
from flask_restful import Api

from yaptide.routes.auth_routes import AuthRegister, AuthLogIn, AuthRefresh, AuthStatus, AuthLogOut
from yaptide.routes.batch_routes import JobsBatch, ResultsBatch
from yaptide.routes.celery_routes import JobsDirect, ConvertInputFiles
from yaptide.routes.task_routes import TaskUpdate
from yaptide.routes.common_sim_routes import SimulationResults, SimulationInputs, SimulationLogfiles
from yaptide.routes.user_routes import UserSimulations, UserClusters, UserUpdate
from yaptide.routes.keycloak_routes import AuthKeycloak


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

    api.add_resource(TaskUpdate, "/tasks/update")

    api.add_resource(SimulationResults, "/results")
    api.add_resource(SimulationInputs, "/inputs")
    api.add_resource(SimulationLogfiles, "/logfiles")

    api.add_resource(ResultsBatch, "/results/batch")

    api.add_resource(ConvertInputFiles, "/convert")

    api.add_resource(UserSimulations, "/user/simulations")
    api.add_resource(UserClusters, "/user/clusters")
    api.add_resource(UserUpdate, "/user/update")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")

    api.add_resource(AuthKeycloak, "/auth/keycloak")
