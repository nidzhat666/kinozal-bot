import redis

from bot.config import REDIS_HOST, REDIS_PORT

redis_client = redis.Redis(REDIS_HOST, REDIS_PORT, decode_responses=True)
