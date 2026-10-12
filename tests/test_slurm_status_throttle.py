"""GET /jobs/batch queries SLURM over SSH at most once per interval and simulation"""

from unittest.mock import Mock

import redis

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
