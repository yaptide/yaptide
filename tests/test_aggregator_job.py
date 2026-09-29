"""The aggregator runs in its own SLURM job, so it can be queued after the tasks it collects from"""

import json
import subprocess
import sys
from pathlib import Path

from yaptide.batch import watcher
from yaptide.batch.shieldhit_string_templates import COLLECT_SHIELDHIT_BASH, SUBMIT_SHIELDHIT
from yaptide.batch.utils.utils import convert_dict_to_aggregator_sbatch_options, extract_aggregator_header


def sbatch_options_as_dict(options: str) -> dict:
    """Parses the rendered sbatch command line back into a dict"""
    return dict(option.lstrip("-").split("=", 1) for option in options.split())


def test_aggregator_options_keep_accounting_and_drop_array_resources():
    """The aggregator has to be accepted by the same queue, but it only forwards updates"""
    payload = {
        "batch_options": {
            "array_options": {
                "time": "12:00:00",
                "account": "plgyaptide-cpu",
                "partition": "plgrid",
                "nodes": "4",
                "ntasks": "48",
                "mem": "16G",
            }
        }
    }

    options = sbatch_options_as_dict(
        convert_dict_to_aggregator_sbatch_options(payload_dict=payload, sim_id=7, job_dir="/scratch/run")
    )

    assert options["account"] == "plgyaptide-cpu"
    assert options["partition"] == "plgrid"
    assert options["time"] == "12:00:00"
    assert "nodes" not in options
    assert (options["ntasks"], options["cpus-per-task"], options["mem"]) == ("1", "1", "1G")
    assert options["job-name"] == "yaptide_aggregator_7"
    assert options["output"] == "/scratch/run/aggregator.log"


def test_watcher_falls_back_to_rest_until_the_aggregator_job_starts(monkeypatch, tmp_path):
    """Tasks may start before the aggregator got its allocation, they have to reach it once it does"""
    posted = []
    monkeypatch.setattr(watcher, "post_task_update", lambda **kwargs: posted.append(kwargs) or True)
    monkeypatch.setattr(watcher, "AGGREGATOR_AUTH_PATH", Path(tmp_path) / ".zmq_auth")
    monkeypatch.setattr(watcher, "AGGREGATOR_SENDER", None)
    monkeypatch.setattr(watcher, "REST_FALLBACK", {"next_progress_seconds": 0.0, "startup_delay_pending": False})
    monkeypatch.setattr(watcher, "REPORTED_STATE", {})

    def update(update_dict: dict) -> dict:
        """Arguments of send_task_update for the given update"""
        return {
            "sim_id": 1,
            "task_id": 2,
            "update_key": "key",
            "backend_url": "http://backend",
            "update_dict": update_dict,
        }

    # the aggregator job is still queued, its auth file does not exist yet - state changes always reach flask,
    # progress alone only every REST_FALLBACK_PROGRESS_INTERVAL_SECONDS, hundreds of tasks share that backend
    assert watcher.send_task_update(**update({"task_state": "RUNNING"}))
    assert watcher.send_task_update(**update({"simulated_primaries": 10}))
    assert watcher.send_task_update(**update({"simulated_primaries": 20}))
    assert watcher.send_task_update(**update({"task_state": "COMPLETED"}))
    assert [kwargs["update_dict"] for kwargs in posted] == [
        {"task_state": "RUNNING"},
        {"simulated_primaries": 10},
        {"task_state": "COMPLETED"},
    ]

    class FakeSender:
        """Aggregator that accepts everything"""

        def __init__(self):
            self.sent = []

        def send(self, task_id: int, update_dict: dict) -> bool:
            """Records the update"""
            self.sent.append((task_id, update_dict))
            return True

    sender = FakeSender()
    monkeypatch.setattr(watcher, "connect_to_aggregator", lambda auth_path, update_key: sender)

    assert watcher.send_task_update(**update({"simulated_primaries": 30}))
    assert len(posted) == 3
    assert sender.sent == [(2, {"simulated_primaries": 30})]


def test_aggregator_options_ignore_unknown_array_options():
    """Anything the user typed into the array options that is not queue placement stays with the array"""
    payload = {"batch_options": {"array_options": {"exclusive": "", "constraint": "intel", "account": "plg-cpu"}}}

    options = sbatch_options_as_dict(
        convert_dict_to_aggregator_sbatch_options(payload_dict=payload, sim_id=1, job_dir="/scratch/run")
    )

    assert options["account"] == "plg-cpu"
    assert "exclusive" not in options and "constraint" not in options


def test_terminal_state_also_goes_straight_to_the_backend(monkeypatch):
    """A send to the aggregator only queues the update - a lost COMPLETED would leave the task RUNNING forever"""
    posted = []
    monkeypatch.setattr(watcher, "post_task_update", lambda **kwargs: posted.append(kwargs["update_dict"]) or True)

    class FakeSender:
        """Aggregator that accepts everything"""

        @staticmethod
        def send(task_id: int, update_dict: dict) -> bool:
            """Accepts the update"""
            return True

    monkeypatch.setattr(watcher, "AGGREGATOR_SENDER", FakeSender())
    monkeypatch.setattr(watcher, "REPORTED_STATE", {})
    arguments = {"sim_id": 1, "task_id": 2, "update_key": "key", "backend_url": "http://backend"}

    running = {"task_state": "RUNNING", "start_time": "2026-09-29 10:00:00.000000", "simulated_primaries": 0}
    assert watcher.send_task_update(update_dict=running, **arguments)
    assert watcher.send_task_update(update_dict={"simulated_primaries": 10}, **arguments)
    assert watcher.send_task_update(update_dict={"task_state": "COMPLETED"}, **arguments)
    # it can overtake the aggregator's batch with RUNNING, after which flask ignores the finished task's start_time
    assert posted == [
        {"task_state": "COMPLETED", "start_time": "2026-09-29 10:00:00.000000", "simulated_primaries": 10}
    ]


def test_first_update_after_connecting_reaches_the_aggregator(tmp_path):
    """The sender waits for the connection, instead of failing its first send and falling back to REST"""
    import zmq  # skipcq: PYL-C0415

    context = zmq.Context()
    pull_socket = context.socket(zmq.PULL)
    port = pull_socket.bind_to_random_port("tcp://127.0.0.1")
    auth_path = Path(tmp_path) / ".zmq_auth"
    auth_path.write_text(json.dumps({"host": "127.0.0.1", "port": port}))

    sender = None
    try:
        sender = watcher.connect_to_aggregator(auth_path, "key")
        assert sender.send(task_id=1, update_dict={"task_state": "RUNNING"})
        assert pull_socket.poll(2000)
    finally:
        pull_socket.close(linger=0)
        context.term()
        if sender is not None:
            sender.close()


def test_watcher_imports_without_pyzmq():
    """Without pyzmq on the cluster the watcher still has to report through REST"""
    code = "import sys; sys.modules['zmq'] = None; import yaptide.batch.watcher as w; print(w.connect_to_aggregator)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_aggregator_starts_with_the_first_array_task_and_collect_stops_it():
    """A dependency on the whole array is satisfied only once its last task started"""
    assert "--dependency=after:${JOB_ID}_1" in SUBMIT_SHIELDHIT.format(
        array_options="",
        collect_options="",
        root_dir="/scratch/run",
        n_tasks="4",
        convertmc_version="2.8.5",
        sim_id=1,
        update_key="key",
        backend_url="http://backend",
        aggregator_options="",
    )
    collect_script = COLLECT_SHIELDHIT_BASH.format(
        collect_header="",
        root_dir="/scratch/run",
        remove_output_from_workspace="true",
        sim_id=1,
        update_key="key",
        backend_url="http://backend",
    )
    assert "scancel `cat $ROOT_DIR/aggregator_job_id`" in collect_script


def test_aggregator_header_keeps_only_queue_placement():
    """Account or partition typed as #SBATCH lines of the array header apply to the aggregator too"""
    array_header = "#SBATCH --account=plg-cpu\n#SBATCH -p plgrid\n#SBATCH --nodes=4\n#SBATCH --mem=16G"
    assert extract_aggregator_header(array_header) == "#SBATCH --account=plg-cpu\n#SBATCH -p plgrid"
    # attached short values, space separated long ones, other options on the same line stay with the array
    array_header = "#SBATCH -Aplg-cpu --exclusive\n#SBATCH --qos normal --comment=x-pz"
    assert extract_aggregator_header(array_header) == "#SBATCH -Aplg-cpu\n#SBATCH --qos normal"
