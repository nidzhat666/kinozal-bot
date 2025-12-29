"""History service for tracking job success/failure."""

import logging
import time

from .models import TranscodeJob, TranscodeStats, RecentHistory
from .redis_client import get_async_client, AsyncRedisClient

logger = logging.getLogger(__name__)


class HistoryService:
    """Tracks job history using Redis lists."""

    MAX_HISTORY = 100

    def __init__(self, redis_client: AsyncRedisClient):
        self._redis = redis_client

    @classmethod
    async def create(cls) -> HistoryService:
        return cls(await get_async_client())

    async def record_success(self, job_id: str, bytes_processed: int = 0) -> None:
        await self._redis.history_add_success(job_id, self.MAX_HISTORY)
        await self._redis.stats_increment("total_success")
        
        if bytes_processed > 0:
            await self._redis.stats_increment("total_bytes_processed", bytes_processed)
        
        await self._redis.stats_set("last_success_at", time.time())
        logger.debug(f"Recorded success: {job_id}")

    async def record_failure(self, job_id: str, error: str | None = None) -> None:
        await self._redis.history_add_failed(job_id, self.MAX_HISTORY)
        await self._redis.stats_increment("total_failed")
        await self._redis.stats_set("last_failed_at", time.time())
        logger.debug(f"Recorded failure: {job_id}")

    async def get_recent_history(self, success_count: int = 10, 
                                 failed_count: int = 5) -> RecentHistory:
        from .queue import get_queue_service
        
        queue = await get_queue_service()
        
        success_ids = await self._redis.history_get_success(success_count)
        failed_ids = await self._redis.history_get_failed(failed_count)

        success_jobs = [j for job_id in success_ids if (j := await queue.get_job(job_id))]
        failed_jobs = [j for job_id in failed_ids if (j := await queue.get_job(job_id))]
        
        stats = TranscodeStats.from_dict(await self._redis.stats_get_all())

        return RecentHistory(success_jobs, failed_jobs, stats)


_history_service: HistoryService | None = None


async def get_history_service() -> HistoryService:
    global _history_service
    if _history_service is None:
        _history_service = await HistoryService.create()
    return _history_service
