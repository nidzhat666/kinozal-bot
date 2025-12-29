"""Metadata management with double marker system (tag + sidecar)."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_PREFIX = "kinozal_transcoded"
SIDECAR_EXT = ".transcoded.json"
CONTAINER_TAG_FIELD = "comment"


@dataclass
class TranscodeMarker:
    version: int = 1
    transcoded_at: float = 0.0
    profile: str = ""
    source_size: int = 0
    source_duration: float = 0.0
    output_size: int = 0
    transcoder: str = "kinozal-bot"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def to_container_tag(self) -> str:
        return f"{MARKER_PREFIX}:v{self.version}:{self.profile}:{int(self.transcoded_at)}"

    @classmethod
    def from_json(cls, json_str: str) -> TranscodeMarker:
        return cls(**json.loads(json_str))

    @classmethod
    def from_container_tag(cls, tag: str) -> TranscodeMarker | None:
        if not tag.startswith(MARKER_PREFIX):
            return None
        parts = tag.split(":")
        if len(parts) < 4:
            return None
        try:
            return cls(version=int(parts[1].lstrip("v")), profile=parts[2],
                      transcoded_at=float(parts[3]))
        except (ValueError, IndexError):
            return None


def get_sidecar_path(file_path: Path | str) -> Path:
    return Path(file_path).with_suffix(Path(file_path).suffix + SIDECAR_EXT)


async def write_sidecar(file_path: Path | str, marker: TranscodeMarker) -> bool:
    try:
        await asyncio.to_thread(get_sidecar_path(file_path).write_text, 
                               marker.to_json(), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Failed to write sidecar for {file_path}: {e}")
        return False


async def read_sidecar(file_path: Path | str) -> TranscodeMarker | None:
    sidecar = get_sidecar_path(file_path)
    if not sidecar.exists():
        return None
    try:
        content = await asyncio.to_thread(sidecar.read_text, encoding="utf-8")
        return TranscodeMarker.from_json(content)
    except Exception:
        return None


async def write_container_tag(file_path: Path | str, marker: TranscodeMarker) -> bool:
    """Write marker to container metadata (MKV only)."""
    file_path = Path(file_path)
    if file_path.suffix.lower() != ".mkv":
        return True

    cmd = ["mkvpropedit", str(file_path), "--edit", "info", 
           "--set", f"title={marker.to_container_tag()}"]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        return proc.returncode == 0
    except FileNotFoundError:
        return True
    except Exception:
        return False


async def read_container_tag(file_path: Path | str) -> TranscodeMarker | None:
    """Read marker from container metadata."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(file_path)]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return None

        tags = json.loads(stdout.decode()).get("format", {}).get("tags", {})
        
        for field in ["title", "comment", "description"]:
            value = tags.get(field) or tags.get(field.upper())
            if value and value.startswith(MARKER_PREFIX):
                return TranscodeMarker.from_container_tag(value)

        return None
    except Exception:
        return None


async def mark_as_transcoded(file_path: Path | str, profile: str, 
                            source_size: int = 0, source_duration: float = 0.0) -> bool:
    """Mark file as transcoded using both markers."""
    try:
        output_size = Path(file_path).stat().st_size
    except OSError:
        output_size = 0

    marker = TranscodeMarker(version=1, transcoded_at=time.time(), profile=profile,
                            source_size=source_size, source_duration=source_duration,
                            output_size=output_size)

    sidecar_ok = await write_sidecar(file_path, marker)
    container_ok = await write_container_tag(file_path, marker)

    return sidecar_ok or container_ok


async def is_transcoded(file_path: Path | str) -> bool:
    """Check if file has been transcoded."""
    return (await read_sidecar(file_path)) is not None or \
           (await read_container_tag(file_path)) is not None


async def needs_transcoding(file_path: Path | str, current_profile: str | None = None) -> bool:
    """Check if file needs transcoding."""
    marker = await read_sidecar(file_path) or await read_container_tag(file_path)
    
    if marker is None:
        return True

    if current_profile and marker.profile != current_profile:
        return True

    return False
