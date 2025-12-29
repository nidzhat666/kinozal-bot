"""Queue service using Redis ZSET for priority management."""

import logging
import time
from dataclasses import dataclass

from .config import get_config
from .models import TranscodeJob, Priority, JobStatus, QueueStats, EnqueueResult
from .redis_client import get_async_client, AsyncRedisClient

logger = logging.getLogger(__name__)


@dataclass
class DequeueResult:
    job: TranscodeJob | None = None
    success: bool = False


class QueueService:
    """Manages transcoding job queue with Redis ZSET."""

    PRIORITY_MULTIPLIER = 1_000_000_000_000_000

    def __init__(self, redis_client: AsyncRedisClient):
        self._redis = redis_client

    @classmethod
    async def create(cls) -> QueueService:
        return cls(await get_async_client())

    def _score(self, priority: Priority, timestamp: float | None = None) -> float:
        ts_ms = int((timestamp or time.time()) * 1000)
        return priority.value * self.PRIORITY_MULTIPLIER + ts_ms

    async def enqueue(self, job: TranscodeJob) -> EnqueueResult:
        """Add job to queue, skip if already exists."""
        job_id = job.job_id
        existing = await self._redis.job_get(job_id)
        
        if existing:
            status = existing.get("status", "pending")
            
            if status in (JobStatus.PROCESSING.value, JobStatus.SUCCESS.value):
                return EnqueueResult(False, job_id, f"already_{status}")
            
            if status == JobStatus.PENDING.value:
                return EnqueueResult(False, job_id, "already_queued")

        job.status = JobStatus.PENDING
        await self._redis.job_set(job_id, job.to_dict())
        score = self._score(job.priority, job.created_at)
        await self._redis.queue_add(job_id, score)
        
        logger.info(f"Enqueued {job_id}: {job.filename} (priority={job.priority.name})")
        return EnqueueResult(True, job_id)

    async def dequeue(self) -> DequeueResult:
        """Pop highest priority job from queue."""
        job_id = await self._redis.queue_pop()
        if not job_id:
            return DequeueResult()

        job_data = await self._redis.job_get(job_id)
        if not job_data:
            logger.warning(f"Orphaned job_id: {job_id}")
            return DequeueResult()

        try:
            return DequeueResult(TranscodeJob.from_dict(job_data), True)
        except Exception as e:
            logger.error(f"Failed to parse job {job_id}: {e}")
            return DequeueResult()

    async def get_job(self, job_id: str) -> TranscodeJob | None:
        job_data = await self._redis.job_get(job_id)
        if not job_data:
            return None
        try:
            return TranscodeJob.from_dict(job_data)
        except Exception as e:
            logger.error(f"Failed to parse job {job_id}: {e}")
            return None

    async def update_job(self, job_id: str, **fields) -> None:
        await self._redis.job_update(job_id, **fields)

    async def set_job_status(self, job_id: str, status: JobStatus) -> None:
        await self._redis.job_update(job_id, status=status.value)

    async def set_job_error(self, job_id: str, error: str, 
                           status: JobStatus = JobStatus.FAILED) -> None:
        await self._redis.job_update(job_id, status=status.value, error_message=error)

    async def increment_attempts(self, job_id: str) -> int:
        job = await self.get_job(job_id)
        if not job:
            return 0
        new_attempts = job.attempts + 1
        await self._redis.job_update(job_id, attempts=new_attempts)
        return new_attempts

    async def requeue_job(self, job_id: str, priority: Priority | None = None) -> bool:
        """Put job back in queue for retry."""
        job = await self.get_job(job_id)
        if not job:
            return False

        await self._redis.job_update(job_id, status=JobStatus.PENDING.value)
        score = self._score(priority or job.priority)
        await self._redis.queue_add(job_id, score)
        logger.info(f"Requeued {job_id}")
        return True

    async def move_to_dlq(self, job_id: str, error: str) -> None:
        """Move job to dead letter queue."""
        await self._redis.job_update(job_id, status=JobStatus.DLQ.value, error_message=error)
        logger.warning(f"Job {job_id} → DLQ: {error}")

    async def delete_job(self, job_id: str) -> None:
        await self._redis.queue_remove(job_id)
        await self._redis.job_delete(job_id)

    async def get_queue_stats(self) -> QueueStats:
        total = await self._redis.queue_size()
        high = await self._redis.queue_count_by_priority(Priority.HIGH, Priority.HIGH)
        low = await self._redis.queue_count_by_priority(Priority.LOW, Priority.LOW)
        processing = await self._redis.lease_count()
        
        return QueueStats(total, high, low, processing)


_queue_service: QueueService | None = None


async def get_queue_service() -> QueueService:
    global _queue_service
    if _queue_service is None:
        _queue_service = await QueueService.create()
    return _queue_service
