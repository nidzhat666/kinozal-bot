"""
Async Redis client wrapper for the transcoding service.
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis

from .config import get_config

logger = logging.getLogger(__name__)

# Global async Redis client instance
_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """
    Get the async Redis client instance.

    Creates the connection on first call.
    """
    global _redis_client

    if _redis_client is None:
        config = get_config()
        _redis_client = aioredis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            decode_responses=True,
        )
        logger.info(
            f"Created async Redis connection: {config.redis_host}:{config.redis_port}/{config.redis_db}"
        )

    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("Closed async Redis connection")


class RedisKeys:
    """Redis key constants for transcoding service."""

    # Queue: ZSET with job_id → score
    QUEUE = "transcode:queue"

    # Job payload: HASH with job fields
    @staticmethod
    def job(job_id: str) -> str:
        return f"transcode:job:{job_id}"

    # Leases: ZSET with job_id → lease_until_epoch_ms
    LEASES = "transcode:leases"

    # Processing info: HASH with worker_id, started_at, progress, eta
    @staticmethod
    def processing(job_id: str) -> str:
        return f"transcode:processing:{job_id}"

    # Worker status: HASH with state, current_job_id, started_at
    @staticmethod
    def worker(worker_id: int) -> str:
        return f"transcode:worker:{worker_id}"

    # History lists
    HISTORY_SUCCESS = "transcode:history:success"
    HISTORY_FAILED = "transcode:history:failed"

    # Stats hash
    STATS = "transcode:stats"


class AsyncRedisClient:
    """
    Wrapper for async Redis operations with transcoding-specific methods.
    """

    def __init__(self, redis: Redis):
        self._redis = redis

    @property
    def redis(self) -> Redis:
        """Direct access to Redis client for advanced operations."""
        return self._redis

    # ==================== Queue Operations ====================

    async def queue_add(self, job_id: str, score: float) -> bool:
        """Add job_id to queue with score. Returns True if added (not existed)."""
        result = await self._redis.zadd(RedisKeys.QUEUE, {job_id: score}, nx=True)
        return result == 1

    async def queue_pop(self) -> str | None:
        """Pop highest priority job_id (lowest score). Returns None if empty."""
        result = await self._redis.zpopmin(RedisKeys.QUEUE, count=1)
        if result:
            job_id, _score = result[0]
            return job_id
        return None

    async def queue_size(self) -> int:
        """Get total queue size."""
        return await self._redis.zcard(RedisKeys.QUEUE)

    async def queue_count_by_priority(self, min_priority: int, max_priority: int) -> int:
        """Count jobs in priority range (scores are priority*1e15 + timestamp)."""
        min_score = min_priority * 1_000_000_000_000_000
        max_score = (max_priority + 1) * 1_000_000_000_000_000 - 1
        return await self._redis.zcount(RedisKeys.QUEUE, min_score, max_score)

    async def queue_remove(self, job_id: str) -> bool:
        """Remove job from queue."""
        result = await self._redis.zrem(RedisKeys.QUEUE, job_id)
        return result == 1

    # ==================== Job Operations ====================

    async def job_exists(self, job_id: str) -> bool:
        """Check if job exists."""
        return await self._redis.exists(RedisKeys.job(job_id)) > 0

    async def job_set(self, job_id: str, data: dict[str, Any]) -> None:
        """Set job data (HSET)."""
        # Convert None values to empty strings for Redis
        clean_data = {k: ("" if v is None else v) for k, v in data.items()}
        await self._redis.hset(RedisKeys.job(job_id), mapping=clean_data)

    async def job_get(self, job_id: str) -> dict[str, str] | None:
        """Get job data (HGETALL). Returns None if not exists."""
        data = await self._redis.hgetall(RedisKeys.job(job_id))
        if not data:
            return None
        # Convert empty strings back to None for optional fields
        return {k: (None if v == "" else v) for k, v in data.items()}

    async def job_update(self, job_id: str, **fields: Any) -> None:
        """Update specific job fields."""
        if fields:
            clean_fields = {k: ("" if v is None else v) for k, v in fields.items()}
            await self._redis.hset(RedisKeys.job(job_id), mapping=clean_fields)

    async def job_delete(self, job_id: str) -> None:
        """Delete job data."""
        await self._redis.delete(RedisKeys.job(job_id))

    async def job_get_field(self, job_id: str, field: str) -> str | None:
        """Get a specific field from job."""
        value = await self._redis.hget(RedisKeys.job(job_id), field)
        return None if value == "" else value

    # ==================== Lease Operations ====================

    async def lease_acquire(self, job_id: str, lease_until: float) -> None:
        """Acquire lease by adding to leases ZSET."""
        await self._redis.zadd(RedisKeys.LEASES, {job_id: lease_until})

    async def lease_release(self, job_id: str) -> None:
        """Release lease by removing from leases ZSET."""
        await self._redis.zrem(RedisKeys.LEASES, job_id)

    async def lease_extend(self, job_id: str, lease_until: float) -> bool:
        """Extend existing lease. Returns True if job had a lease."""
        # XX = only update existing members
        result = await self._redis.zadd(RedisKeys.LEASES, {job_id: lease_until}, xx=True)
        return result == 0  # ZADD XX returns 0 on update, None if not exists

    async def lease_get_expired(self, now: float, limit: int = 100) -> list[str]:
        """Get job_ids with expired leases."""
        return await self._redis.zrangebyscore(
            RedisKeys.LEASES, "-inf", now, start=0, num=limit
        )

    async def lease_count(self) -> int:
        """Count active leases."""
        return await self._redis.zcard(RedisKeys.LEASES)

    # ==================== Processing Info Operations ====================

    async def processing_set(
        self,
        job_id: str,
        worker_id: int,
        started_at: float,
        progress: float = 0.0,
        eta: str | None = None,
    ) -> None:
        """Set processing info for a job."""
        data = {
            "worker_id": worker_id,
            "started_at": started_at,
            "progress": progress,
            "eta": eta or "",
        }
        await self._redis.hset(RedisKeys.processing(job_id), mapping=data)

    async def processing_update_progress(
        self, job_id: str, progress: float, eta: str | None = None, speed: str | None = None
    ) -> None:
        """Update progress for a processing job."""
        data: dict[str, Any] = {"progress": progress}
        if eta is not None:
            data["eta"] = eta
        if speed is not None:
            data["speed"] = speed
        await self._redis.hset(RedisKeys.processing(job_id), mapping=data)

    async def processing_get(self, job_id: str) -> dict[str, str] | None:
        """Get processing info."""
        data = await self._redis.hgetall(RedisKeys.processing(job_id))
        return data if data else None

    async def processing_delete(self, job_id: str) -> None:
        """Delete processing info."""
        await self._redis.delete(RedisKeys.processing(job_id))

    async def processing_get_all(self) -> list[tuple[str, dict]]:
        """Get all processing jobs. Returns list of (job_id, info)."""
        # Get all job_ids from leases
        job_ids = await self._redis.zrange(RedisKeys.LEASES, 0, -1)
        result = []
        for job_id in job_ids:
            info = await self.processing_get(job_id)
            if info:
                result.append((job_id, info))
        return result

    # ==================== Worker Status Operations ====================

    async def worker_set(
        self,
        worker_id: int,
        state: str,
        current_job_id: str | None = None,
        started_at: float | None = None,
    ) -> None:
        """Set worker status."""
        data = {
            "state": state,
            "current_job_id": current_job_id or "",
            "started_at": started_at or "",
        }
        await self._redis.hset(RedisKeys.worker(worker_id), mapping=data)

    async def worker_get(self, worker_id: int) -> dict[str, str] | None:
        """Get worker status."""
        data = await self._redis.hgetall(RedisKeys.worker(worker_id))
        return data if data else None

    async def worker_delete(self, worker_id: int) -> None:
        """Delete worker status."""
        await self._redis.delete(RedisKeys.worker(worker_id))

    # ==================== History Operations ====================

    async def history_add_success(self, job_id: str, max_size: int = 100) -> None:
        """Add job to success history."""
        await self._redis.lpush(RedisKeys.HISTORY_SUCCESS, job_id)
        await self._redis.ltrim(RedisKeys.HISTORY_SUCCESS, 0, max_size - 1)

    async def history_add_failed(self, job_id: str, max_size: int = 100) -> None:
        """Add job to failed history."""
        await self._redis.lpush(RedisKeys.HISTORY_FAILED, job_id)
        await self._redis.ltrim(RedisKeys.HISTORY_FAILED, 0, max_size - 1)

    async def history_get_success(self, count: int = 10) -> list[str]:
        """Get recent successful job_ids."""
        return await self._redis.lrange(RedisKeys.HISTORY_SUCCESS, 0, count - 1)

    async def history_get_failed(self, count: int = 10) -> list[str]:
        """Get recent failed job_ids."""
        return await self._redis.lrange(RedisKeys.HISTORY_FAILED, 0, count - 1)

    # ==================== Stats Operations ====================

    async def stats_increment(self, field: str, amount: int = 1) -> int:
        """Increment a stats field."""
        return await self._redis.hincrby(RedisKeys.STATS, field, amount)

    async def stats_set(self, field: str, value: Any) -> None:
        """Set a stats field."""
        await self._redis.hset(RedisKeys.STATS, field, value)

    async def stats_get_all(self) -> dict[str, str]:
        """Get all stats."""
        return await self._redis.hgetall(RedisKeys.STATS)

    # ==================== Utility Methods ====================

    async def ping(self) -> bool:
        """Check Redis connection."""
        try:
            result = await self._redis.ping()
            return result is True
        except Exception:
            return False


async def get_async_client() -> AsyncRedisClient:
    """Get the async Redis client wrapper."""
    redis = await get_redis()
    return AsyncRedisClient(redis)

