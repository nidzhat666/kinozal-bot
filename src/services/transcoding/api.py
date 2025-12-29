"""
FastAPI endpoints for transcoding service.

Provides:
- POST /transcode/enqueue - Add files to queue (qBittorrent webhook)
- GET /transcode/status - Get current status
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from .config import get_config
from .models import TranscodeJob, Priority, ResolveMode, WorkerState
from .queue import get_queue_service
from .file_resolver import get_folder_resolver
from .file_ops import validate_path_in_roots
from .worker_pool import get_worker_pool
from .history import get_history_service

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/transcode", tags=["transcoding"])


# ==================== Request/Response Models ====================


class EnqueueRequest(BaseModel):
    """Request body for enqueue endpoint."""

    file_path: str
    torrent_hash: str | None = None
    torrent_name: str | None = None  # %N from qBittorrent
    mode: str = "auto"  # movie, series, auto


class QueuedFile(BaseModel):
    """Information about a queued file."""

    job_id: str
    file_path: str


class SkippedFile(BaseModel):
    """Information about a skipped file."""

    file_path: str
    reason: str


class EnqueueResponse(BaseModel):
    """Response for enqueue endpoint."""

    queued: list[QueuedFile]
    skipped: list[SkippedFile]
    errors: list[str]


class WorkerStatusResponse(BaseModel):
    """Worker status information."""

    worker_id: int
    state: str
    current_file: str | None = None
    progress: float = 0.0
    speed: str | None = None
    eta: str | None = None


class QueueStatsResponse(BaseModel):
    """Queue statistics."""

    total: int
    high_priority: int
    low_priority: int
    processing: int


class RecentJobResponse(BaseModel):
    """Recent job information."""

    job_id: str
    file_name: str
    status: str
    error: str | None = None


class StatsResponse(BaseModel):
    """Aggregate statistics."""

    total_success: int
    total_failed: int
    total_bytes_processed: int
    total_bytes_formatted: str
    last_success_ago: str | None = None
    last_failed_ago: str | None = None


class StatusResponse(BaseModel):
    """Full status response."""

    enabled: bool
    workers: list[WorkerStatusResponse]
    queue: QueueStatsResponse
    stats: StatsResponse
    recent_success: list[RecentJobResponse]
    recent_failed: list[RecentJobResponse]


# ==================== Helper Functions ====================


def format_time_ago(timestamp: float | None) -> str | None:
    """Format timestamp as 'X ago' string."""
    if timestamp is None:
        return None

    diff = time.time() - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = int(diff / 60)
        return f"{minutes}m ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours}h ago"
    else:
        days = int(diff / 86400)
        return f"{days}d ago"


def format_bytes(bytes_count: int) -> str:
    """Format bytes as human-readable string."""
    if bytes_count >= 1024 ** 4:
        return f"{bytes_count / (1024 ** 4):.1f} TB"
    elif bytes_count >= 1024 ** 3:
        return f"{bytes_count / (1024 ** 3):.1f} GB"
    elif bytes_count >= 1024 ** 2:
        return f"{bytes_count / (1024 ** 2):.1f} MB"
    elif bytes_count >= 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count} B"


def validate_token(provided_token: str | None) -> None:
    """Validate the API token."""
    config = get_config()

    if not config.api_token:
        # No token configured - skip validation
        return

    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Transcode-Token header",
        )

    if provided_token != config.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# ==================== Endpoints ====================


@router.post("/enqueue", response_model=EnqueueResponse)
async def enqueue_transcode(
    request: EnqueueRequest,
    x_transcode_token: Annotated[str | None, Header()] = None,
) -> EnqueueResponse:
    """
    Add files to the transcoding queue.

    Called by qBittorrent on torrent completion:
    ```bash
    curl -X POST http://host:8000/transcode/enqueue \\
      -H "Content-Type: application/json" \\
      -H "X-Transcode-Token: your-token" \\
      -d '{"file_path": "%F", "torrent_hash": "%I", "torrent_name": "%N"}'
    ```

    The file_path can be a single file or a directory.
    For directories, the resolver will find video files based on mode.
    """
    config = get_config()

    # Validate token
    validate_token(x_transcode_token)

    # Check if transcoding is enabled
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcoding service is disabled",
        )

    # Validate path is in allowed roots
    if not validate_path_in_roots(request.file_path, config.allowed_roots):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Path not in allowed roots: {request.file_path}",
        )

    # Parse mode
    try:
        mode = ResolveMode(request.mode)
    except ValueError:
        mode = ResolveMode.AUTO

    # Resolve files
    resolver = get_folder_resolver()
    resolve_result = resolver.resolve(request.file_path, mode)

    queued: list[QueuedFile] = []
    skipped: list[SkippedFile] = []
    errors: list[str] = []

    # Add skipped files from resolver
    for skip_info in resolve_result.skipped:
        skipped.append(SkippedFile(
            file_path=skip_info.get("file", ""),
            reason=skip_info.get("reason", "unknown"),
        ))

    # Enqueue resolved files
    queue = await get_queue_service()
    profile = config.profile

    for file_path in resolve_result.files:
        try:
            job = TranscodeJob.create(
                file_path=file_path,
                source="qbt",
                priority=Priority.HIGH,  # qBittorrent jobs have high priority
                profile=profile,
                torrent_hash=request.torrent_hash,
                torrent_name=request.torrent_name,
            )

            result = await queue.enqueue(job)

            if result.success:
                queued.append(QueuedFile(
                    job_id=result.job_id or job.job_id,
                    file_path=file_path,
                ))
                logger.info(f"Enqueued from qBt: {file_path}")
            else:
                skipped.append(SkippedFile(
                    file_path=file_path,
                    reason=result.reason or "unknown",
                ))

        except Exception as e:
            logger.error(f"Error enqueueing {file_path}: {e}")
            errors.append(f"{file_path}: {str(e)}")

    return EnqueueResponse(
        queued=queued,
        skipped=skipped,
        errors=errors,
    )


@router.get("/status", response_model=StatusResponse)
async def get_transcode_status() -> StatusResponse:
    """
    Get current transcoding status.

    Returns:
    - Worker statuses (idle/working, progress)
    - Queue statistics
    - Recent completed/failed jobs
    - Aggregate statistics
    """
    config = get_config()

    # Get worker pool status
    pool = get_worker_pool()
    pool_status = await pool.get_status()

    # Format worker statuses
    workers = [
        WorkerStatusResponse(
            worker_id=w.worker_id,
            state=w.state.value,
            current_file=w.current_file,
            progress=w.progress,
            speed=w.speed,
            eta=w.eta,
        )
        for w in pool_status.workers
    ]

    # Queue stats
    queue_stats = QueueStatsResponse(
        total=pool_status.queue_stats.total,
        high_priority=pool_status.queue_stats.high_priority,
        low_priority=pool_status.queue_stats.low_priority,
        processing=pool_status.queue_stats.processing,
    )

    # Get history
    history = await get_history_service()
    recent = await history.get_recent_history(success_count=10, failed_count=5)

    # Format recent jobs
    recent_success = [
        RecentJobResponse(
            job_id=job.job_id,
            file_name=job.filename,
            status=job.status.value,
        )
        for job in recent.success
    ]

    recent_failed = [
        RecentJobResponse(
            job_id=job.job_id,
            file_name=job.filename,
            status=job.status.value,
            error=job.error_message,
        )
        for job in recent.failed
    ]

    # Format stats
    stats = StatsResponse(
        total_success=recent.stats.total_success,
        total_failed=recent.stats.total_failed,
        total_bytes_processed=recent.stats.total_bytes_processed,
        total_bytes_formatted=format_bytes(recent.stats.total_bytes_processed),
        last_success_ago=format_time_ago(recent.stats.last_success_at),
        last_failed_ago=format_time_ago(recent.stats.last_failed_at),
    )

    return StatusResponse(
        enabled=config.enabled,
        workers=workers,
        queue=queue_stats,
        stats=stats,
        recent_success=recent_success,
        recent_failed=recent_failed,
    )

