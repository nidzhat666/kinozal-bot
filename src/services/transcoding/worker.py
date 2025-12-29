"""
FFmpeg worker for video transcoding.

Handles:
- FFmpeg subprocess execution with progress tracking
- Lease management and heartbeat
- Timeout detection for hung processes
- GPU slot acquisition
- Advanced audio processing with stereo fallback
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import get_config
from .models import (
    TranscodeJob,
    JobStatus,
    WorkerState,
    WorkerStatus,
)
from .queue import QueueService
from .lease import LeaseManager
from .file_ops import (
    get_output_paths,
    ensure_tmp_dir,
    cleanup_tmp_file,
    atomic_move,
    TranscodeOutputPaths,
)
from .validation import validate_transcode_output, get_duration
from .metadata import mark_as_transcoded
from .ffmpeg_profiles import (
    get_profile,
    get_audio_tracks,
    build_ffmpeg_command,
    build_simple_ffmpeg_command,
    TranscodeProfile,
)

logger = logging.getLogger(__name__)


@dataclass
class ProgressInfo:
    """FFmpeg progress information."""

    out_time_ms: int = 0
    speed: float = 0.0
    progress: str = "continue"  # "continue" or "end"
    fps: float = 0.0
    bitrate: str = ""


def parse_progress_line(line: str) -> tuple[str, str]:
    """Parse a single progress line (key=value format)."""
    if "=" in line:
        key, _, value = line.partition("=")
        return key.strip(), value.strip()
    return "", ""


def format_eta(seconds: float) -> str:
    """Format seconds as human-readable ETA."""
    if seconds <= 0:
        return ""

    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


class FFmpegWorker:
    """
    Async FFmpeg worker that processes transcoding jobs.

    Features:
    - Reads from priority queue
    - Manages job leases
    - Tracks FFmpeg progress via -progress pipe:1
    - Detects hung processes via progress timeout
    - Supports GPU slot limiting
    """

    def __init__(
        self,
        worker_id: int,
        queue: QueueService,
        lease_manager: LeaseManager,
        gpu_semaphore: asyncio.Semaphore | None = None,
    ):
        self.worker_id = worker_id
        self.queue = queue
        self.lease_manager = lease_manager
        self.gpu_semaphore = gpu_semaphore

        self._config = get_config()
        self._stop_event = asyncio.Event()
        self._process: asyncio.subprocess.Process | None = None
        self._current_job: TranscodeJob | None = None

        # Progress tracking
        self._last_progress_update: float = 0
        self._current_progress: float = 0.0
        self._current_speed: str = ""
        self._current_eta: str = ""

    @property
    def status(self) -> WorkerStatus:
        """Get current worker status."""
        state = WorkerState.IDLE
        if self._stop_event.is_set():
            state = WorkerState.STOPPING
        elif self._current_job is not None:
            state = WorkerState.WORKING

        return WorkerStatus(
            worker_id=self.worker_id,
            state=state,
            current_job_id=self._current_job.job_id if self._current_job else None,
            current_file=self._current_job.filename if self._current_job else None,
            progress=self._current_progress,
            speed=self._current_speed or None,
            eta=self._current_eta or None,
            started_at=self._last_progress_update if self._current_job else None,
        )

    async def run(self) -> None:
        """Main worker loop."""
        logger.info(f"Worker {self.worker_id} started")

        while not self._stop_event.is_set():
            try:
                # Try to get a job
                result = await self.queue.dequeue()

                if not result.success or result.job is None:
                    # No jobs available, wait and retry
                    await asyncio.sleep(2)
                    continue

                job = result.job
                self._current_job = job
                self._reset_progress()

                try:
                    await self._process_job(job)
                except asyncio.CancelledError:
                    # Worker is being stopped
                    await self._handle_job_failure(
                        job, "Worker cancelled", requeue=True
                    )
                    raise
                except Exception as e:
                    logger.exception(f"Worker {self.worker_id} error processing job {job.job_id}")
                    await self._handle_job_failure(job, str(e))
                finally:
                    self._current_job = None
                    self._reset_progress()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Worker {self.worker_id} unexpected error: {e}")
                await asyncio.sleep(5)  # Back off on errors

        logger.info(f"Worker {self.worker_id} stopped")

    async def stop(self) -> None:
        """Signal the worker to stop."""
        self._stop_event.set()

        # Kill any running FFmpeg process
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            except ProcessLookupError:
                pass

    def _reset_progress(self) -> None:
        """Reset progress tracking state."""
        self._last_progress_update = time.time()
        self._current_progress = 0.0
        self._current_speed = ""
        self._current_eta = ""

    async def _process_job(self, job: TranscodeJob) -> None:
        """Process a single transcoding job."""
        logger.info(f"Worker {self.worker_id} processing job {job.job_id}: {job.filename}")

        # Acquire lease
        await self.lease_manager.acquire(
            job.job_id,
            self.worker_id,
            self._config.lease_minutes,
        )

        # Update job status
        await self.queue.set_job_status(job.job_id, JobStatus.PROCESSING)

        # Prepare paths
        paths = get_output_paths(job.file_path)
        await ensure_tmp_dir(paths)

        # Get input duration for progress calculation
        input_duration = await get_duration(job.file_path)

        # Get the transcode profile
        profile = get_profile(job.profile or self._config.profile)

        # Check if GPU is needed
        needs_gpu = "nvenc" in profile.video.codec

        gpu_acquired = False
        try:
            if needs_gpu and self.gpu_semaphore is not None:
                logger.debug(f"Worker {self.worker_id} waiting for GPU slot")
                await self.gpu_semaphore.acquire()
                gpu_acquired = True
                logger.debug(f"Worker {self.worker_id} acquired GPU slot")

            # Get audio tracks for advanced processing
            audio_tracks = await get_audio_tracks(paths.input_path)
            logger.debug(f"Found {len(audio_tracks)} audio tracks")

            # Run FFmpeg
            success = await self._run_ffmpeg(job, paths, profile, audio_tracks, input_duration)

            if not success:
                await self._handle_job_failure(job, "FFmpeg failed")
                return

            # Validate output
            validation = await validate_transcode_output(
                paths.input_path,
                paths.tmp_path,
            )

            if not validation.valid:
                error_msg = "; ".join(validation.errors)
                await cleanup_tmp_file(paths)
                await self._handle_job_failure(job, f"Validation failed: {error_msg}")
                return

            # Atomic move to final location
            move_success = await atomic_move(paths)
            if not move_success:
                await self._handle_job_failure(job, "Failed to move output file")
                return

            # Add transcode markers
            await mark_as_transcoded(
                paths.output_path,
                profile=profile.name,
                source_size=job.file_size,
                source_duration=input_duration,
            )

            # Success!
            await self._handle_job_success(job, paths.output_path)

        finally:
            if gpu_acquired and self.gpu_semaphore is not None:
                self.gpu_semaphore.release()
                logger.debug(f"Worker {self.worker_id} released GPU slot")

            # Release lease
            await self.lease_manager.release(job.job_id)

    async def _run_ffmpeg(
        self,
        job: TranscodeJob,
        paths: TranscodeOutputPaths,
        profile: TranscodeProfile,
        audio_tracks: list,
        input_duration: float,
    ) -> bool:
        """
        Run FFmpeg transcoding process.

        Returns True on success.
        """
        # Build FFmpeg command using the profile system
        if audio_tracks and profile.create_stereo_fallback:
            # Use advanced command with audio track processing
            cmd = build_ffmpeg_command(
                paths.input_path,
                paths.tmp_path,
                profile,
                audio_tracks,
            )
        else:
            # Use simple command without audio analysis
            cmd = build_simple_ffmpeg_command(
                paths.input_path,
                paths.tmp_path,
                profile,
            )

        logger.info(f"FFmpeg command: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Read progress from stdout
            progress_task = asyncio.create_task(
                self._read_progress(job.job_id, input_duration)
            )

            # Monitor for timeout
            timeout_task = asyncio.create_task(
                self._monitor_timeout(job.job_id)
            )

            try:
                await self._process.wait()
            finally:
                progress_task.cancel()
                timeout_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass

            # Check result
            if self._process.returncode != 0:
                stderr = await self._process.stderr.read() if self._process.stderr else b""
                logger.error(
                    f"FFmpeg failed for {job.job_id} with code {self._process.returncode}: "
                    f"{stderr.decode()[:500]}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"FFmpeg execution error for {job.job_id}: {e}")
            return False
        finally:
            self._process = None

    async def _read_progress(self, job_id: str, duration: float) -> None:
        """Read and parse FFmpeg progress output."""
        if self._process is None or self._process.stdout is None:
            return

        progress_info = ProgressInfo()

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                decoded = line.decode().strip()
                key, value = parse_progress_line(decoded)

                if key == "out_time_ms":
                    if value != "N/A":
                        try:
                            progress_info.out_time_ms = int(value)
                        except ValueError:
                            pass

                elif key == "speed":
                    if value != "N/A":
                        # Parse "1.5x" format
                        match = re.match(r"([\d.]+)x", value)
                        if match:
                            progress_info.speed = float(match.group(1))
                            self._current_speed = value

                elif key == "progress":
                    progress_info.progress = value

                # Update progress percentage
                if duration > 0 and progress_info.out_time_ms > 0:
                    current_seconds = progress_info.out_time_ms / 1_000_000
                    self._current_progress = min(100, (current_seconds / duration) * 100)

                    # Calculate ETA
                    if progress_info.speed > 0:
                        remaining_seconds = (duration - current_seconds) / progress_info.speed
                        self._current_eta = format_eta(remaining_seconds)

                    # Update lease progress
                    self._last_progress_update = time.time()
                    await self.lease_manager.update_progress(
                        job_id,
                        self._current_progress,
                        eta=self._current_eta,
                        speed=self._current_speed,
                    )

                # Check for completion
                if progress_info.progress == "end":
                    self._current_progress = 100.0
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error reading progress: {e}")
                continue

    async def _monitor_timeout(self, job_id: str) -> None:
        """Monitor for progress timeout (hung FFmpeg)."""
        timeout_seconds = self._config.progress_timeout_minutes * 60

        while True:
            await asyncio.sleep(30)  # Check every 30 seconds

            if self._process is None:
                break

            elapsed = time.time() - self._last_progress_update
            if elapsed > timeout_seconds:
                logger.error(
                    f"Progress timeout for job {job_id}: "
                    f"no update for {elapsed:.0f}s (limit: {timeout_seconds}s)"
                )

                # Kill the process
                if self._process is not None:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                break

    async def _handle_job_success(
        self,
        job: TranscodeJob,
        output_path: Path,
    ) -> None:
        """Handle successful job completion."""
        # Import here to avoid circular dependency
        from .history import get_history_service

        try:
            output_size = output_path.stat().st_size
        except OSError:
            output_size = 0

        await self.queue.set_job_status(job.job_id, JobStatus.SUCCESS)

        # Record in history
        history = await get_history_service()
        await history.record_success(job.job_id, output_size)

        logger.info(
            f"Worker {self.worker_id} completed job {job.job_id}: "
            f"{job.filename} ({output_size / 1024 / 1024:.1f} MB)"
        )

    async def _handle_job_failure(
        self,
        job: TranscodeJob,
        error: str,
        requeue: bool = False,
    ) -> None:
        """Handle job failure."""
        from .history import get_history_service

        logger.error(f"Worker {self.worker_id} job {job.job_id} failed: {error}")

        # Increment attempts
        new_attempts = await self.queue.increment_attempts(job.job_id)

        if requeue and new_attempts < self._config.max_attempts:
            # Requeue for retry
            await self.queue.requeue_job(job.job_id)
            logger.info(
                f"Job {job.job_id} requeued (attempt {new_attempts}/{self._config.max_attempts})"
            )
        elif new_attempts >= self._config.max_attempts:
            # Move to DLQ
            await self.queue.move_to_dlq(job.job_id, error)
            history = await get_history_service()
            await history.record_failure(job.job_id, error)
        else:
            # Mark as failed
            await self.queue.set_job_error(job.job_id, error, JobStatus.FAILED)
            history = await get_history_service()
            await history.record_failure(job.job_id, error)

