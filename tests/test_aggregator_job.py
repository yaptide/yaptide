"""The aggregator runs in its own SLURM job, so it can be queued after the tasks it collects from"""

from pathlib import Path

from yaptide.batch import watcher
from yaptide.batch.utils.utils import convert_dict_to_aggregator_sbatch_options


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
    monkeypatch.setattr(watcher, "REST_FALLBACK", {"last_progress_seconds": 0.0})

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
