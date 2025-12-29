"""
FFmpeg encoding profiles.

Includes advanced NVENC profile with stereo fallback audio tracks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AudioTrackInfo:
    """Information about an audio track."""

    index: int  # Stream index in container
    codec: str
    channels: int
    language: str | None = None
    title: str | None = None


@dataclass
class VideoProfile:
    """Video encoding settings."""

    codec: str
    preset: str
    tune: str | None = None
    rate_control: str = "vbr"
    cq: int = 21  # Constant quality
    maxrate: str = "25M"
    bufsize: str = "50M"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class AudioProfile:
    """Audio encoding settings for fallback stereo track."""

    codec: str = "aac"
    bitrate: str = "192k"
    # Downmix 5.1 -> stereo with proper mixing
    # pan: center/surround mixed in
    # dynaudnorm: loudness normalization
    # alimiter: prevent clipping
    stereo_filter: str = (
        "pan=stereo|c0=0.707*c0+0.5*c2+0.5*c4|c1=0.707*c1+0.5*c2+0.5*c5,"
        "dynaudnorm=f=150:g=15,"
        "alimiter=limit=0.98"
    )


@dataclass
class TranscodeProfile:
    """Complete transcoding profile."""

    name: str
    description: str
    video: VideoProfile
    audio: AudioProfile
    # Whether to create stereo fallback for each audio track
    create_stereo_fallback: bool = True
    # Copy subtitles
    copy_subtitles: bool = True
    # Preserve metadata and chapters
    preserve_metadata: bool = True
    # Add faststart flag (useful for streaming)
    faststart: bool = True


# ============================================================================
# Predefined Profiles
# ============================================================================

PROFILES: dict[str, TranscodeProfile] = {
    # Main optimization profile matching optimize.sh
    "nvenc_hevc_optimized": TranscodeProfile(
        name="nvenc_hevc_optimized",
        description="NVENC HEVC with stereo fallback audio (matches optimize.sh)",
        video=VideoProfile(
            codec="hevc_nvenc",
            preset="p6",
            tune="hq",
            rate_control="vbr",
            cq=21,
            maxrate="25M",
            bufsize="50M",
        ),
        audio=AudioProfile(
            codec="aac",
            bitrate="192k",
        ),
        create_stereo_fallback=True,
    ),
    # High quality NVENC for 4K content
    "nvenc_hevc_4k": TranscodeProfile(
        name="nvenc_hevc_4k",
        description="NVENC HEVC optimized for 4K content",
        video=VideoProfile(
            codec="hevc_nvenc",
            preset="p5",  # Slightly faster for 4K
            tune="hq",
            rate_control="vbr",
            cq=23,  # Slightly lower quality for size
            maxrate="50M",
            bufsize="100M",
        ),
        audio=AudioProfile(
            codec="aac",
            bitrate="256k",
        ),
        create_stereo_fallback=True,
    ),
    # Fast NVENC for quick processing
    "nvenc_hevc_fast": TranscodeProfile(
        name="nvenc_hevc_fast",
        description="Fast NVENC HEVC encoding",
        video=VideoProfile(
            codec="hevc_nvenc",
            preset="p4",
            tune="ll",  # Low latency
            rate_control="vbr",
            cq=24,
            maxrate="20M",
            bufsize="40M",
        ),
        audio=AudioProfile(
            codec="aac",
            bitrate="192k",
        ),
        create_stereo_fallback=False,  # Skip for speed
    ),
    # CPU fallback with x265
    "cpu_hevc_medium": TranscodeProfile(
        name="cpu_hevc_medium",
        description="CPU x265 encoding (no GPU required)",
        video=VideoProfile(
            codec="libx265",
            preset="medium",
            tune=None,
            rate_control="crf",
            cq=23,
            maxrate="",
            bufsize="",
            extra_args=["-crf", "23", "-tag:v", "hvc1"],
        ),
        audio=AudioProfile(
            codec="aac",
            bitrate="192k",
        ),
        create_stereo_fallback=True,
    ),
    # Copy video, only process audio
    "audio_only": TranscodeProfile(
        name="audio_only",
        description="Copy video, create stereo fallback audio only",
        video=VideoProfile(
            codec="copy",
            preset="",
            tune=None,
            rate_control="",
            cq=0,
            maxrate="",
            bufsize="",
        ),
        audio=AudioProfile(
            codec="aac",
            bitrate="192k",
        ),
        create_stereo_fallback=True,
    ),
}


def get_profile(name: str) -> TranscodeProfile:
    """Get a profile by name."""
    if name not in PROFILES:
        logger.warning(f"Profile '{name}' not found, using nvenc_hevc_optimized")
        return PROFILES["nvenc_hevc_optimized"]
    return PROFILES[name]


async def get_audio_tracks(file_path: Path | str) -> list[AudioTrackInfo]:
    """
    Get audio track information from a file using ffprobe.

    Returns list of AudioTrackInfo for each audio stream.
    """
    file_path = Path(file_path)

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "a",
        str(file_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            return []

        data = json.loads(stdout.decode())
        streams = data.get("streams", [])

        tracks = []
        for i, stream in enumerate(streams):
            tracks.append(AudioTrackInfo(
                index=stream.get("index", i),
                codec=stream.get("codec_name", "unknown"),
                channels=stream.get("channels", 2),
                language=stream.get("tags", {}).get("language"),
                title=stream.get("tags", {}).get("title"),
            ))

        return tracks

    except Exception as e:
        logger.error(f"Failed to get audio tracks from {file_path}: {e}")
        return []


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    profile: TranscodeProfile,
    audio_tracks: list[AudioTrackInfo],
) -> list[str]:
    """
    Build complete FFmpeg command based on profile.

    Implements the logic from optimize.sh:
    - Video encoding with NVENC
    - For each audio track: copy original + create stereo fallback
    - Copy subtitles
    - Preserve metadata/chapters
    """
    args = ["ffmpeg", "-y"]

    # Input
    args.extend(["-i", str(input_path)])

    # Map video (first video stream)
    args.extend(["-map", "0:v:0"])

    # Map subtitles (if any)
    if profile.copy_subtitles:
        args.extend(["-map", "0:s?", "-c:s", "copy"])

    # Preserve metadata and chapters
    if profile.preserve_metadata:
        args.extend(["-map_metadata", "0", "-map_chapters", "0"])

    # Video encoding
    if profile.video.codec == "copy":
        args.extend(["-c:v", "copy"])
    elif "nvenc" in profile.video.codec:
        # NVENC specific settings
        args.extend([
            "-c:v", profile.video.codec,
            "-preset", profile.video.preset,
        ])
        if profile.video.tune:
            args.extend(["-tune", profile.video.tune])
        args.extend([
            "-rc", profile.video.rate_control,
            "-cq", str(profile.video.cq),
            "-b:v", "0",
            "-maxrate", profile.video.maxrate,
            "-bufsize", profile.video.bufsize,
        ])
    else:
        # CPU encoding (libx265, libx264)
        args.extend(["-c:v", profile.video.codec])
        if profile.video.preset:
            args.extend(["-preset", profile.video.preset])
        args.extend(profile.video.extra_args)

    # Audio handling
    if not audio_tracks:
        # No audio tracks - just skip audio
        pass
    elif profile.create_stereo_fallback:
        # For each audio track: original (copy) + stereo fallback
        for i, track in enumerate(audio_tracks):
            # Stream index for this audio track
            a_idx = i

            # 1) Original audio (copy)
            args.extend(["-map", f"0:a:{a_idx}"])
            args.extend([f"-c:a:{2*i}", "copy"])

            # 2) Stereo fallback
            args.extend(["-map", f"0:a:{a_idx}"])
            args.extend([f"-filter:a:{2*i+1}", profile.audio.stereo_filter])
            args.extend([f"-c:a:{2*i+1}", profile.audio.codec])
            args.extend([f"-b:a:{2*i+1}", profile.audio.bitrate])

            # Disposition: stereo as default for better compatibility
            args.extend([f"-disposition:a:{2*i}", "0"])
            args.extend([f"-disposition:a:{2*i+1}", "default"])

            # Metadata for clarity
            original_title = track.title or "Original"
            args.extend([f"-metadata:s:a:{2*i}", f"title={original_title}"])
            args.extend([f"-metadata:s:a:{2*i+1}", "title=Stereo (Normalized)"])
    else:
        # Just copy all audio tracks
        args.extend(["-map", "0:a", "-c:a", "copy"])

    # Faststart for streaming
    if profile.faststart:
        args.extend(["-movflags", "+faststart"])

    # Progress output
    args.extend(["-progress", "pipe:1"])

    # Output
    args.append(str(output_path))

    return args


def build_simple_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    profile: TranscodeProfile,
) -> list[str]:
    """
    Build simple FFmpeg command without audio track analysis.

    Used when we can't probe audio tracks or for simple profiles.
    """
    args = ["ffmpeg", "-y", "-i", str(input_path)]

    # Video
    if profile.video.codec == "copy":
        args.extend(["-c:v", "copy"])
    elif "nvenc" in profile.video.codec:
        args.extend([
            "-c:v", profile.video.codec,
            "-preset", profile.video.preset,
        ])
        if profile.video.tune:
            args.extend(["-tune", profile.video.tune])
        args.extend([
            "-rc", profile.video.rate_control,
            "-cq", str(profile.video.cq),
            "-b:v", "0",
            "-maxrate", profile.video.maxrate,
            "-bufsize", profile.video.bufsize,
        ])
    else:
        args.extend(["-c:v", profile.video.codec])
        if profile.video.preset:
            args.extend(["-preset", profile.video.preset])
        args.extend(profile.video.extra_args)

    # Audio - just copy
    args.extend(["-c:a", "copy"])

    # Subtitles
    if profile.copy_subtitles:
        args.extend(["-c:s", "copy"])

    # Metadata
    if profile.preserve_metadata:
        args.extend(["-map_metadata", "0", "-map_chapters", "0"])

    # Faststart
    if profile.faststart:
        args.extend(["-movflags", "+faststart"])

    # Progress
    args.extend(["-progress", "pipe:1"])

    args.append(str(output_path))

    return args

