"""Worker pool manager for FFmpeg transcoding."""

import asyncio
import logging
from dataclasses import dataclass

from .config import get_config
from .models import WorkerStatus, WorkerState, QueueStats
from .queue import get_queue_service
from .lease import get_lease_manager
from .worker import FFmpegWorker

logger = logging.getLogger(__name__)


@dataclass
class PoolStatus:
    workers: list[WorkerStatus]
    queue_stats: QueueStats
    active_workers: int
    idle_workers: int


class WorkerPool:
    """Manages FFmpeg workers with GPU slot limiting."""

    REAPER_INTERVAL = 60

    def __init__(self, num_workers: int | None = None, gpu_slots: int | None = None):
        config = get_config()
        self.num_workers = num_workers or config.workers
        self.gpu_slots = gpu_slots or config.gpu_slots

        self._workers: list[FFmpegWorker] = []
        self._worker_tasks: list[asyncio.Task] = []
        self._reaper_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        self._gpu_semaphore = asyncio.Semaphore(gpu_slots) if gpu_slots > 0 else None
        self._queue = None
        self._lease_manager = None

    async def start(self) -> None:
        logger.info(f"Starting worker pool: {self.num_workers} workers, {self.gpu_slots} GPU slots")

        self._queue = await get_queue_service()
        self._lease_manager = await get_lease_manager()

        for i in range(self.num_workers):
            worker = FFmpegWorker(i, self._queue, self._lease_manager, self._gpu_semaphore)
            self._workers.append(worker)
            self._worker_tasks.append(asyncio.create_task(worker.run(), name=f"worker-{i}"))

        self._reaper_task = asyncio.create_task(self._run_reaper(), name="lease-reaper")
        logger.info("Worker pool started")

    async def stop(self) -> None:
        logger.info("Stopping worker pool...")
        self._stop_event.set()

        for worker in self._workers:
            await worker.stop()

        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)

        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        self._workers.clear()
        self._worker_tasks.clear()
        logger.info("Worker pool stopped")

    async def _run_reaper(self) -> None:
        logger.info("Lease reaper started")
        
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.REAPER_INTERVAL)
                if not self._stop_event.is_set() and self._lease_manager:
                    await self._lease_manager.reap_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reaper error: {e}")

        logger.info("Lease reaper stopped")

    async def get_status(self) -> PoolStatus:
        worker_statuses = [w.status for w in self._workers]
        active = sum(1 for w in worker_statuses if w.state == WorkerState.WORKING)
        idle = sum(1 for w in worker_statuses if w.state == WorkerState.IDLE)
        queue_stats = await self._queue.get_queue_stats() if self._queue else QueueStats()

        return PoolStatus(worker_statuses, queue_stats, active, idle)

    @property
    def is_running(self) -> bool:
        return len(self._workers) > 0 and not self._stop_event.is_set()


_worker_pool: WorkerPool | None = None


def get_worker_pool() -> WorkerPool:
    global _worker_pool
    if _worker_pool is None:
        _worker_pool = WorkerPool()
    return _worker_pool


async def start_worker_pool() -> WorkerPool:
    pool = get_worker_pool()
    if not pool.is_running:
        await pool.start()
    return pool


async def stop_worker_pool() -> None:
    global _worker_pool
    if _worker_pool:
        await _worker_pool.stop()
        _worker_pool = None
