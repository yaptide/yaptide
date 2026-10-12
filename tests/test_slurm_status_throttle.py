import redis

from yaptide.routes import batch_routes


class FakeRedis:
    def __init__(self):
        self.keys = set()

    def set(self, key, _value, nx, ex):
        assert nx and ex == batch_routes.SLURM_STATUS_INTERVAL
        if key in self.keys:
            return None
        self.keys.add(key)
        return True


class BrokenRedis:
    def set(self, *_args, **_kwargs):
        raise redis.ConnectionError("down")


def test_slurm_status_checked_once_per_interval(monkeypatch):
    monkeypatch.setattr(batch_routes, "_redis", FakeRedis())
    assert batch_routes.slurm_status_due(1)
    assert not batch_routes.slurm_status_due(1)
    assert batch_routes.slurm_status_due(2)


def test_slurm_status_always_checked_without_redis(monkeypatch):
    monkeypatch.setattr(batch_routes, "_redis", None)
    assert batch_routes.slurm_status_due(1)
    assert batch_routes.slurm_status_due(1)
    monkeypatch.setattr(batch_routes, "_redis", BrokenRedis())
    assert batch_routes.slurm_status_due(1)
