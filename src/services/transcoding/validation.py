"""Output validation using ffprobe and decode tests."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MediaInfo:
    duration: float = 0.0
    video_streams: int = 0
    audio_streams: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    format_name: str = ""
    file_size: int = 0


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    input_info: MediaInfo | None = None
    output_info: MediaInfo | None = None


async def get_media_info(file_path: Path | str) -> MediaInfo | None:
    """Get media info using ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", 
           "-show_streams", str(file_path)]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return None

        data = json.loads(stdout.decode())
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        info = MediaInfo(
            duration=float(fmt.get("duration", 0)),
            file_size=int(fmt.get("size", 0)),
            format_name=fmt.get("format_name", ""),
        )

        for stream in streams:
            if stream.get("codec_type") == "video":
                info.video_streams += 1
                if not info.video_codec:
                    info.video_codec = stream.get("codec_name", "")
                    info.width = int(stream.get("width", 0))
                    info.height = int(stream.get("height", 0))
            elif stream.get("codec_type") == "audio":
                info.audio_streams += 1
                if not info.audio_codec:
                    info.audio_codec = stream.get("codec_name", "")

        return info
    except Exception as e:
        logger.error(f"ffprobe error for {file_path}: {e}")
        return None


async def get_duration(file_path: Path | str) -> float:
    info = await get_media_info(file_path)
    return info.duration if info else 0.0


async def quick_decode_test(file_path: Path | str, duration: float = 60.0) -> tuple[bool, str | None]:
    """Quick decode test on first N seconds."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(file_path), "-t", str(duration), "-f", "null", "-"]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            return False, f"Decode failed: {stderr.decode()[:500]}"

        return True, None
    except Exception as e:
        return False, f"Decode error: {e}"


async def validate_transcode_output(input_path: Path | str, output_path: Path | str,
                                   duration_tolerance: float = 2.0,
                                   decode_test_duration: float = 60.0) -> ValidationResult:
    """Validate transcoded output file."""
    output_path = Path(output_path)
    result = ValidationResult()

    if not output_path.exists():
        result.valid = False
        result.errors.append("Output file does not exist")
        return result

    try:
        if output_path.stat().st_size == 0:
            result.valid = False
            result.errors.append("Output file is empty")
            return result
    except OSError as e:
        result.valid = False
        result.errors.append(f"Cannot stat output: {e}")
        return result

    input_info = await get_media_info(input_path)
    output_info = await get_media_info(output_path)

    result.input_info = input_info
    result.output_info = output_info

    if not output_info:
        result.valid = False
        result.errors.append("Cannot get output file info")
        return result

    if input_info and output_info:
        duration_diff = abs(input_info.duration - output_info.duration)
        if duration_diff > duration_tolerance:
            result.valid = False
            result.errors.append(f"Duration mismatch: {duration_diff:.1f}s")

    if output_info.video_streams == 0:
        result.valid = False
        result.errors.append("No video streams")
    elif output_info.width == 0 or output_info.height == 0:
        result.valid = False
        result.errors.append(f"Invalid resolution: {output_info.width}x{output_info.height}")

    if output_info.audio_streams == 0:
        result.valid = False
        result.errors.append("No audio streams")

    if result.valid:
        decode_ok, decode_error = await quick_decode_test(output_path, decode_test_duration)
        if not decode_ok:
            result.valid = False
            result.errors.append(decode_error or "Decode test failed")

    return result
