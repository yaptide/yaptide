"""GET /jobs/batch: SLURM queried over SSH at most once per interval and simulation, and the state it reports"""

from unittest.mock import Mock

import redis

from yaptide.batch import batch_methods
from yaptide.routes import batch_routes


def test_slurm_status_checked_once_per_interval(monkeypatch):
    """Redis lets the first caller of an interval through and answers None to the others"""
    client = Mock()
    client.set.side_effect = [True, None]
    monkeypatch.setattr(batch_routes, "_redis", client)
    assert batch_routes.slurm_status_due(7)
    assert not batch_routes.slurm_status_due(7)
    client.set.assert_called_with("slurm_status:7", 1, nx=True, ex=batch_routes.SLURM_STATUS_INTERVAL)


def test_slurm_status_always_checked_without_redis(monkeypatch):
    """Without a working Redis every request queries SLURM, as before the throttle"""
    monkeypatch.setattr(batch_routes, "_redis", None)
    assert batch_routes.slurm_status_due(7)
    client = Mock()
    client.set.side_effect = redis.ConnectionError("down")
    monkeypatch.setattr(batch_routes, "_redis", client)
    assert batch_routes.slurm_status_due(7)


def test_job_status_pending_until_a_task_starts(monkeypatch):
    """The simulation shows PENDING while every array task waits in the queue, RUNNING once one has started"""
    sacct = {"1": "", "2": "     State \n---------- \n   PENDING \n"}

    def status(array_lines):
        sacct["1"] = "     State \n---------- \n" + "".join(f"{line} \n" for line in array_lines)
        connection = Mock()
        connection.run.side_effect = lambda command, hide: Mock(stdout=sacct[command.split()[2]])
        monkeypatch.setattr(batch_methods, "get_connection", lambda user, cluster: connection)
        simulation = Mock(array_id=1, collect_id=2)
        return batch_methods.get_job_status(simulation=simulation, user=None, cluster=None)["job_state"]

    assert status(["PENDING"]) == "PENDING"
    assert status(["RUNNING", "RUNNING", "RUNNING", "PENDING"]) == "RUNNING"
    assert status(["COMPLETED", "COMPLETED", "PENDING"]) == "RUNNING"
