"""Library scanner for finding files to transcode."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import get_config
from .models import TranscodeJob, Priority
from .queue import get_queue_service
from .file_resolver import (is_video_extension, is_partial_file, is_extras_file,
                            MIN_FILE_SIZE)
from .file_ops import is_file_stable
from .metadata import needs_transcoding

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scanned: int = 0
    queued: int = 0
    skipped_done: int = 0
    skipped_queued: int = 0
    skipped_unstable: int = 0
    skipped_other: int = 0
    errors: int = 0


class LibraryScanner:
    """Scans library directories for videos to transcode."""

    def __init__(self, scan_paths: list[str] | None = None, 
                 scan_interval_hours: int | None = None):
        config = get_config()
        self.scan_paths = [Path(p) for p in (scan_paths or config.scan_paths)]
        self.scan_interval_hours = scan_interval_hours or config.scan_interval_hours
        self.profile = config.profile
        
        self._stop_event = asyncio.Event()
        self._queue = None

    async def run(self) -> None:
        if not self.scan_paths:
            logger.warning("No scan paths configured")
            return

        logger.info(f"Library scanner started: {self.scan_paths}, interval={self.scan_interval_hours}h")
        self._queue = await get_queue_service()

        await self.scan_all()

        interval = self.scan_interval_hours * 3600
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                await self.scan_all()
            except asyncio.CancelledError:
                break

        logger.info("Library scanner stopped")

    def stop(self) -> None:
        self._stop_event.set()

    async def scan_all(self) -> ScanResult:
        result = ScanResult()
        
        for path in self.scan_paths:
            if not path.exists():
                logger.warning(f"Scan path not found: {path}")
                continue

            r = await self._scan_path(path)
            result.scanned += r.scanned
            result.queued += r.queued
            result.skipped_done += r.skipped_done
            result.skipped_queued += r.skipped_queued
            result.skipped_unstable += r.skipped_unstable
            result.skipped_other += r.skipped_other
            result.errors += r.errors

        logger.info(f"Scan complete: {result.scanned} scanned, {result.queued} queued, "
                   f"{result.skipped_done} done")
        return result

    async def _scan_path(self, path: Path) -> ScanResult:
        result = ScanResult()
        
        try:
            video_files = [f for f in path.rglob("*") if f.is_file() and is_video_extension(f)]
        except PermissionError:
            result.errors += 1
            return result

        for vf in video_files:
            result.scanned += 1
            status = await self._process_file(vf)
            
            if status == "queued":
                result.queued += 1
            elif status == "already_done":
                result.skipped_done += 1
            elif status == "already_queued":
                result.skipped_queued += 1
            elif status == "unstable":
                result.skipped_unstable += 1
            elif status == "error":
                result.errors += 1
            else:
                result.skipped_other += 1

            if result.scanned % 100 == 0:
                await asyncio.sleep(0)

        return result

    async def _process_file(self, file_path: Path) -> str:
        """Process file for queuing."""
        if is_partial_file(file_path) or is_extras_file(file_path):
            return "skip"

        try:
            if file_path.stat().st_size < MIN_FILE_SIZE:
                return "skip"
        except OSError:
            return "error"

        if not await is_file_stable(file_path, 10.0, 120.0):
            return "unstable"

        if not await needs_transcoding(file_path, self.profile):
            return "already_done"

        job = TranscodeJob.create(file_path=str(file_path), source="scanner",
                                 priority=Priority.LOW, profile=self.profile)

        result = await self._queue.enqueue(job)
        
        if result.success:
            logger.debug(f"Queued from scan: {file_path}")
            return "queued"
        
        return result.reason or "error"


_scanner: LibraryScanner | None = None
_scanner_task: asyncio.Task | None = None


def get_scanner() -> LibraryScanner:
    global _scanner
    if _scanner is None:
        _scanner = LibraryScanner()
    return _scanner


async def start_scanner() -> LibraryScanner:
    global _scanner, _scanner_task
    scanner = get_scanner()

    if _scanner_task is None or _scanner_task.done():
        _scanner_task = asyncio.create_task(scanner.run(), name="library-scanner")

    return scanner


async def stop_scanner() -> None:
    global _scanner, _scanner_task

    if _scanner:
        _scanner.stop()

    if _scanner_task:
        _scanner_task.cancel()
        try:
            await _scanner_task
        except asyncio.CancelledError:
            pass
        _scanner_task = None

    _scanner = None
