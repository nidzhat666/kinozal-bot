"""
FFmpeg Transcoding Service

Provides asynchronous video transcoding with:
- Priority queue (Redis ZSET)
- Lease-based job management
- Multiple FFmpeg workers
- Library scanning

Usage:
    from services.transcoding.config import get_config
    from services.transcoding.models import TranscodeJob, Priority
    from services.transcoding.worker_pool import start_worker_pool, stop_worker_pool
    from services.transcoding.scanner import start_scanner, stop_scanner
    from services.transcoding.api import router as transcode_router
"""

# Only import non-Redis-dependent modules at package level
from .models import TranscodeJob, Priority, JobStatus, WorkerState, ResolveMode
from .config import TranscodeConfig, get_config

__all__ = [
    # Models (always available)
    "TranscodeJob",
    "Priority",
    "JobStatus",
    "WorkerState",
    "ResolveMode",
    # Config (always available)
    "TranscodeConfig",
    "get_config",
]

