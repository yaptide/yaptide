from flask_restful import Api, Resource

from yaptide.routes.auth_routes import (AuthLogIn, AuthLogOut, AuthRefresh,
                                        AuthRegister, AuthStatus)
from yaptide.routes.batch_routes import Clusters, JobsBatch
from yaptide.routes.celery_routes import ConvertResource, JobsDirect
from yaptide.routes.common_sim_routes import (JobsResource,
                                              InputsResource,
                                              LogfilesResource,
                                              ResultsResource)
from yaptide.routes.keycloak_routes import AuthKeycloak
from yaptide.routes.task_routes import TasksResource
from yaptide.routes.user_routes import UserSimulations, UserUpdate
from yaptide.routes.utils.response_templates import yaptide_response


class HelloWorld(Resource):
    """Root route"""

    @staticmethod
    def get():
        """Root route get method"""
        return yaptide_response(message="Hello World!", code=200)


def initialize_routes(api: Api):
    """Function initializing routes"""
    api.add_resource(HelloWorld, "/")

    api.add_resource(JobsDirect, "/jobs/direct")
    api.add_resource(JobsBatch, "/jobs/batch")

    api.add_resource(JobsResource, "/jobs")

    api.add_resource(TasksResource, "/tasks")

    api.add_resource(ResultsResource, "/results")
    api.add_resource(InputsResource, "/inputs")
    api.add_resource(LogfilesResource, "/logfiles")

    api.add_resource(ConvertResource, "/convert")

    api.add_resource(UserSimulations, "/user/simulations")
    api.add_resource(UserUpdate, "/user/update")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")

    api.add_resource(AuthKeycloak, "/auth/keycloak")

    api.add_resource(Clusters, "/clusters")
