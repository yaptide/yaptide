import os
import redis

redis_url = os.environ.get('REDIS_URL')
if redis_url == 'FAKE_REDIS':
    from fakeredis import FakeRedis, FakeServer
    redis_client = FakeRedis(server=FakeServer())
else:
    redis_client = redis.from_url(redis_url)

def get_redis_client():
    return redis_client