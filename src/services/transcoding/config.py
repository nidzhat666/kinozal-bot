"""
Transcoding configuration from environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import Literal


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse boolean from env string."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def _parse_list(value: str | None, default: list[str] | None = None) -> list[str]:
    """Parse comma-separated list from env string."""
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int(value: str | None, default: int) -> int:
    """Parse int from env string."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class TranscodeConfig:
    """Transcoding service configuration."""

    # Core settings
    enabled: bool = False
    workers: int = 3
    api_token: str = ""

    # Paths
    scan_paths: list[str] = field(default_factory=list)
    allowed_roots: list[str] = field(default_factory=list)
    scan_interval_hours: int = 6

    # Lease/Retry
    lease_minutes: int = 60
    max_attempts: int = 3
    progress_timeout_minutes: int = 10

    # Output handling
    replace_original: bool = False
    output_suffix: str = ".optimized"
    keep_backup_hours: int = 72

    # GPU
    gpu_slots: int = 0  # 0 = CPU only

    # FFmpeg profile name (from ffmpeg_profiles.py)
    # Available: nvenc_hevc_optimized, nvenc_hevc_4k, nvenc_hevc_fast, 
    #            cpu_hevc_medium, audio_only
    profile: str = "nvenc_hevc_optimized"

    # Folder resolver
    default_mode: Literal["movie", "series", "auto"] = "auto"
    max_files_per_enqueue: int = 50

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    @classmethod
    def from_env(cls) -> "TranscodeConfig":
        """Load configuration from environment variables."""
        return cls(
            # Core
            enabled=_parse_bool(os.getenv("TRANSCODE_ENABLED"), False),
            workers=_parse_int(os.getenv("TRANSCODE_WORKERS"), 3),
            api_token=os.getenv("TRANSCODE_API_TOKEN", ""),
            # Paths
            scan_paths=_parse_list(os.getenv("TRANSCODE_SCAN_PATHS")),
            allowed_roots=_parse_list(os.getenv("TRANSCODE_ALLOWED_ROOTS")),
            scan_interval_hours=_parse_int(
                os.getenv("TRANSCODE_SCAN_INTERVAL_HOURS"), 6
            ),
            # Lease/Retry
            lease_minutes=_parse_int(os.getenv("TRANSCODE_LEASE_MINUTES"), 60),
            max_attempts=_parse_int(os.getenv("TRANSCODE_MAX_ATTEMPTS"), 3),
            progress_timeout_minutes=_parse_int(
                os.getenv("TRANSCODE_PROGRESS_TIMEOUT_MINUTES"), 10
            ),
            # Output
            replace_original=_parse_bool(
                os.getenv("TRANSCODE_REPLACE_ORIGINAL"), False
            ),
            output_suffix=os.getenv("TRANSCODE_OUTPUT_SUFFIX", ".optimized"),
            keep_backup_hours=_parse_int(os.getenv("TRANSCODE_KEEP_BACKUP_HOURS"), 72),
            # GPU
            gpu_slots=_parse_int(os.getenv("TRANSCODE_GPU_SLOTS"), 0),
            # FFmpeg profile
            profile=os.getenv("FFMPEG_PROFILE", "nvenc_hevc_optimized"),
            # Folder resolver
            default_mode=os.getenv("TRANSCODE_DEFAULT_MODE", "auto"),  # type: ignore
            max_files_per_enqueue=_parse_int(
                os.getenv("TRANSCODE_MAX_FILES_PER_ENQUEUE"), 50
            ),
            # Redis
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=_parse_int(os.getenv("REDIS_PORT"), 6379),
            redis_db=_parse_int(os.getenv("REDIS_DB"), 0),
        )


# Global config instance (lazy loaded)
_config: TranscodeConfig | None = None


def get_config() -> TranscodeConfig:
    """Get the global transcoding configuration."""
    global _config
    if _config is None:
        _config = TranscodeConfig.from_env()
    return _config


def reload_config() -> TranscodeConfig:
    """Reload configuration from environment."""
    global _config
    _config = TranscodeConfig.from_env()
    return _config
