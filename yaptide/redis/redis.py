import os
import redis

redis_url = os.environ.get('REDIS_URL')
redis_client = redis.from_url(redis_url)