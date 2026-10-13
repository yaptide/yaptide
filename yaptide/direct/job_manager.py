import os
from contextlib import contextmanager
from typing import Iterator

# the supervisor of a simulation must be ready within this time; the UI gives up on a submit after 30 s
START_TIMEOUT_SECONDS = 20


@contextmanager
def ray_connection() -> Iterator[None]:
    """Connects to the Ray cluster for one request - Flask workers do not keep a connection between requests"""
    import ray  # skipcq: PYL-C0415 # imported here, as every gunicorn worker imports the routes but few submit

    if ray.is_initialized():
        yield
        return
    address = os.environ.get("RAY_ADDRESS")
    if not address:
        raise RuntimeError("RAY_ADDRESS is not set, direct simulations cannot be run")
    from yaptide.direct.supervisor import NAMESPACE  # skipcq: PYL-C0415

    ray.init(address=address, namespace=NAMESPACE, log_to_driver=False)
    try:
        yield
    finally:
        ray.shutdown()


def submit_simulation(simulation_id: int, update_key: str, files_dict: dict, ntasks: int, sim_type: str) -> str:
    """Starts the supervisor of a simulation, which runs it to the end, and returns the supervisor's name"""
    import ray  # skipcq: PYL-C0415
    from yaptide.direct.supervisor import SimulationSupervisor, supervisor_name  # skipcq: PYL-C0415

    name = supervisor_name(simulation_id)
    with ray_connection():
        supervisor = SimulationSupervisor.options(name=name, lifetime="detached").remote(simulation_id, update_key)
        try:
            ray.get(supervisor.start.remote(files_dict, ntasks, sim_type), timeout=START_TIMEOUT_SECONDS)
        except BaseException:
            # the simulation is reported as not started, so it must not run anyway
            ray.kill(supervisor, no_restart=True)
            raise
    return name


def submit_batch_job(**submit_kwargs) -> None:
    """Hands an HPC job to the submitter on the Ray cluster, returning once the submitter has it"""
    import ray  # skipcq: PYL-C0415
    from ray.exceptions import ActorAlreadyExistsError  # skipcq: PYL-C0415
    from yaptide.batch.submitter import SUBMITTER_NAME, BatchSubmitter  # skipcq: PYL-C0415

    with ray_connection():
        # a detached actor, as Ray kills a plain task once this request disconnects; created by the first submit
        # after the Ray head starts, and again if it ever dies
        submitter = BatchSubmitter.options(name=SUBMITTER_NAME, lifetime="detached", get_if_exists=True).remote()
        try:
            ray.get(submitter.submit.remote(**submit_kwargs), timeout=START_TIMEOUT_SECONDS)
        except ActorAlreadyExistsError:
            # through Ray Client the actor is created only now - another request was quicker, its actor serves both
            ray.get(ray.get_actor(SUBMITTER_NAME).submit.remote(**submit_kwargs), timeout=START_TIMEOUT_SECONDS)


def cancel_simulation(simulation_id: int) -> bool:
    """Stops all tasks of a simulation; False when its supervisor is already gone"""
    import ray  # skipcq: PYL-C0415
    from ray.exceptions import RayActorError  # skipcq: PYL-C0415
    from yaptide.direct.supervisor import supervisor_name  # skipcq: PYL-C0415

    with ray_connection():
        try:
            supervisor = ray.get_actor(supervisor_name(simulation_id))
            ray.get(supervisor.cancel.remote())
        except (ValueError, RayActorError):
            # the supervisor has already finished (or just finished), there is nothing left to stop
            return False
    return True
