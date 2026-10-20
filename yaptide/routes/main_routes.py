from flask_restful import Api, Resource

from yaptide.batch.merge_results import DISPLAY_MAX_BINS, MAX_OUTPUT_BYTES

from yaptide.routes.auth_routes import AuthLogIn, AuthLogOut, AuthRefresh, AuthRegister, AuthStatus
from yaptide.routes.batch_routes import Clusters, JobsBatch
from yaptide.routes.direct_routes import JobsDirect
from yaptide.routes.common_sim_routes import (
    FullResolutionResource,
    InputsResource,
    JobsResource,
    LogfilesResource,
    ResultsResource,
)
from yaptide.routes.estimator_routes import EstimatorResource
from yaptide.routes.events_routes import SimulationsEventsResource
from yaptide.routes.keycloak_routes import AuthKeycloak
from yaptide.routes.results_upload_routes import ResultsDoneResource, ResultsUploadsResource
from yaptide.routes.task_routes import TaskLinksResource, TasksBulkResource, TasksResource
from yaptide.routes.user_routes import UserSimulations, UserUpdate
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import local_users_enabled


class HelloWorld(Resource):
    """Root route"""

    @staticmethod
    def get():
        """Root route get method, also advertising which login methods are available to the UI"""
        return yaptide_response(
            message="Hello World!",
            code=200,
            content={
                "local_users_enabled": local_users_enabled(),
                # the limits the UI mirrors (yaptide/batch/merge_results.py)
                "max_output_bytes": MAX_OUTPUT_BYTES,
                "display_max_bins": DISPLAY_MAX_BINS,
            },
        )


def initialize_routes(api: Api):
    """Function initializing routes"""
    api.add_resource(HelloWorld, "/")

    api.add_resource(JobsDirect, "/jobs/direct")
    api.add_resource(JobsBatch, "/jobs/batch")

    api.add_resource(JobsResource, "/jobs")

    api.add_resource(TasksResource, "/tasks")
    api.add_resource(TasksBulkResource, "/tasks/bulk")
    api.add_resource(TaskLinksResource, "/tasks/links")

    api.add_resource(ResultsResource, "/results")
    api.add_resource(FullResolutionResource, "/results/full_resolution")
    api.add_resource(ResultsUploadsResource, "/results/uploads")
    api.add_resource(ResultsDoneResource, "/results/done")
    api.add_resource(InputsResource, "/inputs")
    api.add_resource(LogfilesResource, "/logfiles")
    # served by the yaptide_events server, nginx sends /events/ there
    api.add_resource(SimulationsEventsResource, "/events/simulations")

    api.add_resource(UserSimulations, "/user/simulations")
    api.add_resource(UserUpdate, "/user/update")

    api.add_resource(AuthRegister, "/auth/register")
    api.add_resource(AuthLogIn, "/auth/login")
    api.add_resource(AuthRefresh, "/auth/refresh")
    api.add_resource(AuthStatus, "/auth/status")
    api.add_resource(AuthLogOut, "/auth/logout")

    api.add_resource(AuthKeycloak, "/auth/keycloak")

    api.add_resource(Clusters, "/clusters")
    api.add_resource(EstimatorResource, "/estimators")
