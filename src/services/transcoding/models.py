"""Transcoding data models."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum, Enum
from pathlib import Path
from typing import Literal


class Priority(IntEnum):
    HIGH = 0
    LOW = 10


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    DLQ = "dlq"


class WorkerState(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    STOPPING = "stopping"


class ResolveMode(str, Enum):
    MOVIE = "movie"
    SERIES = "series"
    AUTO = "auto"


SCHEMA_VERSION = 1


@dataclass
class TranscodeJob:
    """Video transcoding job."""

    job_id: str
    file_path: str
    source: Literal["qbt", "scanner"]
    priority: Priority
    profile: str
    created_at: float
    v: int = SCHEMA_VERSION
    torrent_hash: str | None = None
    torrent_name: str | None = None
    attempts: int = 0
    status: JobStatus = JobStatus.PENDING
    error_message: str | None = None
    file_size: int = 0

    @staticmethod
    def make_job_id(file_path: str, profile: str, schema_v: int = SCHEMA_VERSION) -> str:
        """Generate unique job ID: sha1(path:size:mtime:profile:v)."""
        try:
            path = Path(file_path).resolve()
            stat = path.stat()
            data = f"{file_path}:{stat.st_size}:{int(stat.st_mtime)}:{profile}:{schema_v}"
        except (OSError, FileNotFoundError):
            data = f"{file_path}:0:0:{profile}:{schema_v}"
        
        return hashlib.sha1(data.encode()).hexdigest()[:16]

    @classmethod
    def create(cls, file_path: str, source: Literal["qbt", "scanner"], 
               priority: Priority, profile: str, torrent_hash: str | None = None,
               torrent_name: str | None = None) -> TranscodeJob:
        """Create new job with auto-generated job_id."""
        job_id = cls.make_job_id(file_path, profile)
        
        try:
            file_size = Path(file_path).stat().st_size
        except (OSError, FileNotFoundError):
            file_size = 0

        return cls(job_id=job_id, file_path=file_path, source=source, priority=priority,
                   profile=profile, created_at=time.time(), torrent_hash=torrent_hash,
                   torrent_name=torrent_name, file_size=file_size)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["priority"] = self.priority.value
        data["status"] = self.status.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> TranscodeJob:
        return cls(
            job_id=data["job_id"],
            file_path=data["file_path"],
            source=data["source"],
            priority=Priority(int(data["priority"])),
            profile=data["profile"],
            created_at=float(data["created_at"]),
            v=int(data.get("v", SCHEMA_VERSION)),
            torrent_hash=data.get("torrent_hash"),
            torrent_name=data.get("torrent_name"),
            attempts=int(data.get("attempts", 0)),
            status=JobStatus(data.get("status", "pending")),
            error_message=data.get("error_message"),
            file_size=int(data.get("file_size", 0)),
        )

    @classmethod
    def from_json(cls, json_str: str) -> TranscodeJob:
        return cls.from_dict(json.loads(json_str))

    @property
    def filename(self) -> str:
        return os.path.basename(self.file_path)


@dataclass
class WorkerStatus:
    worker_id: int
    state: WorkerState
    current_job_id: str | None = None
    current_file: str | None = None
    progress: float = 0.0
    speed: str | None = None
    eta: str | None = None
    started_at: float | None = None

    def to_dict(self) -> dict:
        return {k: (v.value if isinstance(v, Enum) else v) 
                for k, v in asdict(self).items()}


@dataclass
class QueueStats:
    total: int = 0
    high_priority: int = 0
    low_priority: int = 0
    processing: int = 0


@dataclass
class TranscodeStats:
    total_success: int = 0
    total_failed: int = 0
    total_bytes_processed: int = 0
    last_success_at: float | None = None
    last_failed_at: float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> TranscodeStats:
        safe_int = lambda v, d=0: int(v) if v else d
        safe_float = lambda v: float(v) if v else None
        return cls(
            total_success=safe_int(data.get("total_success")),
            total_failed=safe_int(data.get("total_failed")),
            total_bytes_processed=safe_int(data.get("total_bytes_processed")),
            last_success_at=safe_float(data.get("last_success_at")),
            last_failed_at=safe_float(data.get("last_failed_at")),
        )


@dataclass
class EnqueueResult:
    success: bool
    job_id: str | None = None
    reason: str | None = None


@dataclass
class ResolveResult:
    files: list[str] = field(default_factory=list)
    mode_used: ResolveMode = ResolveMode.AUTO
    skipped: list[dict] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    input_duration: float = 0.0
    output_duration: float = 0.0


@dataclass
class RecentHistory:
    success: list[TranscodeJob] = field(default_factory=list)
    failed: list[TranscodeJob] = field(default_factory=list)
    stats: TranscodeStats = field(default_factory=TranscodeStats)

