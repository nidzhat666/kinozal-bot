"""Lease manager for job processing with O(log N) reaper."""

import logging
import time
from dataclasses import dataclass

from .config import get_config
from .models import JobStatus
from .redis_client import get_async_client, AsyncRedisClient

logger = logging.getLogger(__name__)


@dataclass
class LeaseInfo:
    job_id: str
    worker_id: int
    started_at: float
    lease_until: float
    progress: float = 0.0
    eta: str | None = None
    speed: str | None = None


class LeaseManager:
    """Manages job leases using Redis ZSET for O(log N) expiry checking."""

    def __init__(self, redis_client: AsyncRedisClient):
        self._redis = redis_client
        self._config = get_config()

    @classmethod
    async def create(cls) -> LeaseManager:
        return cls(await get_async_client())

    def _lease_until(self, ttl_minutes: int | None = None) -> float:
        ttl = ttl_minutes or self._config.lease_minutes
        return time.time() * 1000 + (ttl * 60 * 1000)

    async def acquire(self, job_id: str, worker_id: int, ttl_minutes: int | None = None) -> bool:
        lease_until = self._lease_until(ttl_minutes)
        await self._redis.lease_acquire(job_id, lease_until)
        await self._redis.processing_set(job_id, worker_id, time.time())
        logger.debug(f"Lease acquired: job={job_id}, worker={worker_id}")
        return True

    async def release(self, job_id: str) -> None:
        await self._redis.lease_release(job_id)
        await self._redis.processing_delete(job_id)
        logger.debug(f"Lease released: job={job_id}")

    async def extend(self, job_id: str, ttl_minutes: int | None = None) -> bool:
        lease_until = self._lease_until(ttl_minutes)
        success = await self._redis.lease_extend(job_id, lease_until)
        if success:
            logger.debug(f"Lease extended: job={job_id}")
        return success

    async def update_progress(self, job_id: str, progress: float, 
                            eta: str | None = None, speed: str | None = None) -> None:
        await self._redis.processing_update_progress(job_id, progress, eta, speed)

    async def reap_expired(self) -> list[str]:
        """Find expired leases and requeue or move to DLQ."""
        from .queue import get_queue_service

        now_ms = time.time() * 1000
        expired_ids = await self._redis.lease_get_expired(now_ms)
        if not expired_ids:
            return []

        queue = await get_queue_service()
        reaped = []

        for job_id in expired_ids:
            try:
                await self.release(job_id)
                job = await queue.get_job(job_id)
                
                if not job:
                    logger.warning(f"Expired lease for non-existent job: {job_id}")
                    continue

                new_attempts = await queue.increment_attempts(job_id)

                if new_attempts >= self._config.max_attempts:
                    await queue.move_to_dlq(job_id, f"Max attempts ({self._config.max_attempts}) exceeded")
                else:
                    await queue.requeue_job(job_id)
                    logger.info(f"Job {job_id} requeued (attempt {new_attempts}/{self._config.max_attempts})")

                reaped.append(job_id)
            except Exception as e:
                logger.error(f"Error reaping {job_id}: {e}")

        if reaped:
            logger.info(f"Reaped {len(reaped)} expired leases")

        return reaped


_lease_manager: LeaseManager | None = None


async def get_lease_manager() -> LeaseManager:
    global _lease_manager
    if _lease_manager is None:
        _lease_manager = await LeaseManager.create()
    return _lease_manager
