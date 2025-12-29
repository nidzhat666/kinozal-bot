"""File operations for atomic transcoding."""

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .config import get_config

logger = logging.getLogger(__name__)

TMP_DIR = ".transcode_tmp"
BACKUP_SUFFIX = ".bak"


@dataclass
class TranscodeOutputPaths:
    input_path: Path
    output_path: Path
    tmp_path: Path
    tmp_dir: Path
    backup_path: Path | None


def get_output_paths(input_path: str | Path) -> TranscodeOutputPaths:
    """Calculate paths for transcoding operation."""
    config = get_config()
    input_path = Path(input_path)
    tmp_dir = input_path.parent / TMP_DIR
    tmp_path = tmp_dir / f"{input_path.stem}.tmp.mkv"

    if config.replace_original:
        output_path = input_path.with_suffix(".mkv")
        backup_path = input_path.with_suffix(input_path.suffix + BACKUP_SUFFIX)
    else:
        suffix = config.output_suffix or ".optimized"
        output_path = input_path.with_stem(input_path.stem + suffix).with_suffix(".mkv")
        backup_path = None

    return TranscodeOutputPaths(input_path, output_path, tmp_path, tmp_dir, backup_path)


async def ensure_tmp_dir(paths: TranscodeOutputPaths) -> None:
    await asyncio.to_thread(paths.tmp_dir.mkdir, parents=True, exist_ok=True)


async def cleanup_tmp_file(paths: TranscodeOutputPaths) -> None:
    if paths.tmp_path.exists():
        try:
            await asyncio.to_thread(paths.tmp_path.unlink)
        except OSError:
            pass


async def atomic_move(paths: TranscodeOutputPaths, create_backup: bool = True) -> bool:
    """Atomically move transcoded file to final location."""
    config = get_config()

    try:
        if not paths.tmp_path.exists() or paths.tmp_path.stat().st_size == 0:
            return False

        if config.replace_original and create_backup and paths.backup_path:
            if paths.input_path.exists():
                await asyncio.to_thread(shutil.move, str(paths.input_path), str(paths.backup_path))

        await asyncio.to_thread(shutil.move, str(paths.tmp_path), str(paths.output_path))
        logger.info(f"Moved output to: {paths.output_path}")

        if paths.tmp_dir.exists() and not any(paths.tmp_dir.iterdir()):
            await asyncio.to_thread(paths.tmp_dir.rmdir)

        return True
    except Exception as e:
        logger.error(f"Atomic move failed: {e}")
        return False


async def is_file_stable(path: Path | str, check_interval: float = 30.0, 
                        min_age: float = 120.0) -> bool:
    """Check if file is stable (not being written)."""
    path = Path(path)

    try:
        stat1 = await asyncio.to_thread(path.stat)
    except OSError:
        return False

    if (time.time() - stat1.st_mtime) < min_age:
        return False

    await asyncio.sleep(check_interval)

    try:
        stat2 = await asyncio.to_thread(path.stat)
    except OSError:
        return False

    return stat1.st_size == stat2.st_size


def validate_path_in_roots(path: str, allowed_roots: list[str]) -> bool:
    """Check if path is within allowed roots."""
    if not allowed_roots:
        return True

    try:
        real_path = os.path.realpath(path)
    except OSError:
        return False

    for root in allowed_roots:
        try:
            real_root = os.path.realpath(root)
            if real_path.startswith(real_root + os.sep) or real_path == real_root:
                return True
        except OSError:
            continue

    return False
