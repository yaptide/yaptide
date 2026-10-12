"""Direct simulations on a local Ray cluster: the supervisor, its batched status updates, merge and cancel"""

import itertools
import json
import os
import platform
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import ray

from yaptide.direct.job_manager import cancel_simulation, submit_simulation
from yaptide.direct.simulation import WORK_DIR_PREFIX
from yaptide.direct.supervisor import NAMESPACE, supervisor_name

pytestmark = pytest.mark.skipif(platform.system() == "Windows", reason="the fake simulator is a POSIX script")

FAKE_SIMULATOR_DIR = Path(__file__).resolve().parent / "res" / "fake_shieldhit"
REPO_DIR = Path(__file__).resolve().parent.parent
# every submit gets a new simulation id, so a rerun test never meets a supervisor or requests of an earlier run
SIMULATION_IDS = itertools.count(1000)
FLUKA_MOCK_DIR = REPO_DIR / "yaptide" / "fake"


class BackendStub(BaseHTTPRequestHandler):
    """Stands in for Flask: accepts every request from the supervisor and records it"""

    requests: list = []

    def do_POST(self):
        """Records the path and the JSON body, answers like the backend does"""
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        BackendStub.requests.append((self.path, body))
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"message": "ok"}')

    def log_message(self, *_):  # skipcq: PYL-R0201
        """Keeps the test output quiet"""


@pytest.fixture(scope="module")
def backend_url():
    """URL of a stub backend recording the requests of the supervisors"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), BackendStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def work_root(tmp_path_factory) -> Path:
    """Directory where the tasks create their working directories"""
    return tmp_path_factory.mktemp("ray_work")


@pytest.fixture(scope="module")
def ray_cluster(backend_url: str, work_root: Path):
    """A local Ray cluster whose workers find the fake simulator and the stub backend"""
    env_vars = {
        "PATH": os.pathsep.join([str(FAKE_SIMULATOR_DIR), str(FLUKA_MOCK_DIR), os.environ["PATH"]]),
        "BACKEND_INTERNAL_URL": backend_url,
        "TMPDIR": str(work_root),
        "PYTHONPATH": str(REPO_DIR),
    }
    ray.init(num_cpus=4, namespace=NAMESPACE, runtime_env={"env_vars": env_vars}, include_dashboard=False)
    yield
    ray.shutdown()


def wait_for(condition, timeout: float = 60) -> bool:
    """Polls until the condition holds or the timeout passes"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.2)
    return False


def requests_of(simulation_id: int) -> list:
    """Requests the stub backend got for one simulation"""
    return [
        (path, body)
        for path, body in BackendStub.requests
        if body.get("simulation_id", body.get("sim_id")) == simulation_id
    ]


def supervisor_gone(simulation_id: int) -> bool:
    """True once the supervisor actor of the simulation has exited"""
    try:
        ray.get_actor(supervisor_name(simulation_id))
    except ValueError:
        return True
    return False


def test_simulation_runs_merges_and_reports_in_batches(ray_cluster, work_root: Path):
    """Two tasks run, their states arrive in bulk requests only, the merged results are sent and all is cleaned up"""
    sim_id = next(SIMULATION_IDS)  # skipcq: PTC-W0063
    submit_simulation(sim_id, "key", {"beam.dat": "regular run"}, ntasks=2, sim_type="shieldhit")

    assert wait_for(lambda: any(path == "/results" for path, _ in requests_of(sim_id)))
    assert wait_for(lambda: supervisor_gone(sim_id))
    sent = requests_of(sim_id)
    paths = [path for path, _ in sent]
    assert "/tasks" not in paths
    final_states = {}
    for path, body in sent:
        if path == "/tasks/bulk":
            for task in body["tasks"]:
                final_states.setdefault(task["task_id"], {}).update(task["update_dict"])
    assert {task_id: state["task_state"] for task_id, state in final_states.items()} == {0: "COMPLETED", 1: "COMPLETED"}
    # the monitor read the simulator's log: the start of each task arrived through the supervisor too
    assert all("start_time" in state for state in final_states.values())
    results = [body for path, body in sent if path == "/results"][0]
    assert [estimator["name"] for estimator in results["estimators"]] == ["entrance", "peak", "yz_profile", "z_profile"]
    assert ("/jobs", {"sim_id": sim_id, "update_key": "key", "job_state": "MERGING_RUNNING"}) in sent
    assert not list(work_root.glob(f"{WORK_DIR_PREFIX}{sim_id}_*"))


def test_failed_tasks_mark_the_simulation_failed(ray_cluster):
    """When every task fails, the tasks and then the simulation are reported FAILED"""
    sim_id = next(SIMULATION_IDS)  # skipcq: PTC-W0063
    submit_simulation(sim_id, "key", {"beam.dat": "FAKE_FAIL"}, ntasks=2, sim_type="shieldhit")

    assert wait_for(lambda: any(body.get("job_state") == "FAILED" for _, body in requests_of(sim_id)))
    states = {
        task["task_id"]: task["update_dict"]["task_state"]
        for path, body in requests_of(sim_id)
        if path == "/tasks/bulk"
        for task in body["tasks"]
        if "task_state" in task["update_dict"]
    }
    assert states == {0: "FAILED", 1: "FAILED"}
    assert "/results" not in [path for path, _ in requests_of(sim_id)]


def test_cancel_kills_the_simulator_and_cleans_up(ray_cluster, work_root: Path):
    """Cancel stops the running simulator processes, removes the working directories and sends nothing more"""
    sim_id = next(SIMULATION_IDS)  # skipcq: PTC-W0063
    submit_simulation(sim_id, "key", {"beam.dat": "FAKE_SLEEP"}, ntasks=2, sim_type="shieldhit")
    pid_files = [work_root / f"{WORK_DIR_PREFIX}{sim_id}_{task_id}" / "fake.pid" for task_id in range(2)]
    assert wait_for(lambda: all(pid_file.exists() for pid_file in pid_files))
    pids = [int(pid_file.read_text()) for pid_file in pid_files]

    assert cancel_simulation(sim_id)

    def all_dead() -> bool:
        """True when none of the fake simulator processes is alive"""
        for pid in pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            return False
        return True

    assert wait_for(all_dead, timeout=30)
    assert wait_for(lambda: supervisor_gone(sim_id), timeout=30)
    assert not list(work_root.glob(f"{WORK_DIR_PREFIX}{sim_id}_*"))
    assert not [path for path, _ in requests_of(sim_id) if path in ("/results", "/jobs")]


def test_cancel_of_a_finished_simulation_reports_missing_supervisor(ray_cluster):
    """Cancelling a simulation whose supervisor already exited is not an error"""
    assert not cancel_simulation(999)


def test_fluka_mock_results(ray_cluster, fluka_payload_files_dict_data: dict):
    """FLUKA results of two tasks are merged into the values the FLUKA mock produces"""
    sim_id = next(SIMULATION_IDS)  # skipcq: PTC-W0063
    submit_simulation(sim_id, "key", fluka_payload_files_dict_data["input_files"], ntasks=2, sim_type="fluka")

    assert wait_for(lambda: any(path == "/results" for path, _ in requests_of(sim_id)))
    estimators = [body for path, body in requests_of(sim_id) if path == "/results"][0]["estimators"]
    expected = {
        "21": [[0.0, 0.0, 0.0, 0.0], [0.0, 1.46468, 1.69978, 0.0], [0.9081, 0.0, 0.0, 0.0], [0, 0.0, 0.0, 0.0]],
        "22": [
            [0.4757, 0.0, 0.0, 0.0],
            [0.0, 1.88021, 1.66488, 0.0],
            [0.0, 1.0242, 1.05254, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
    }
    assert [estimator["name"] for estimator in estimators] == ["21", "22"]
    for estimator in estimators:
        assert len(estimator["pages"]) == 1
        values = np.around(np.flip(np.array(estimator["pages"][0]["data"]["values"]), []).flatten(), 4)
        np.testing.assert_array_equal(
            values, np.around(np.swapaxes(np.array(expected[estimator["name"]]), 0, 1).flatten(), 4)
        )
