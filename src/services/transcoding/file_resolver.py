"""Folder resolver for extracting video files from paths."""

import logging
import re
from pathlib import Path

from .models import ResolveMode, ResolveResult

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", 
                     ".webm", ".flv", ".ts", ".m2ts", ".mts", ".vob"}

PARTIAL_PATTERNS = [r"\.part$", r"\.partial$", r"\.tmp$", r"\.!qb$", r"\.!ut$"]

EPISODE_PATTERNS = [
    r"[Ss](\d{1,2})[Ee](\d{1,2})", r"(\d{1,2})x(\d{1,2})",
    r"[Ss]eason\s*(\d+)", r"[Ee]pisode\s*(\d+)", r"[Ee]p\.?\s*(\d+)",
]

EXTRAS_PATTERNS = [
    r"\bextras?\b", r"\bfeaturettes?\b", r"\bbehind[.\s_-]*the[.\s_-]*scenes?\b",
    r"\bdeleted[.\s_-]*scenes?\b", r"\btrailers?\b", r"\bsamples?\b",
    r"\binterviews?\b", r"\bbonus\b", r"\bspecials?\b", r"\bmaking[.\s_-]*of\b",
]

MIN_FILE_SIZE = 50 * 1024 * 1024


def is_video_extension(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_partial_file(path: Path) -> bool:
    return any(re.search(p, path.name.lower(), re.I) for p in PARTIAL_PATTERNS)


def is_extras_file(path: Path) -> bool:
    parts = [path.name.lower()] + [p.lower() for p in path.parts[:-1]]
    full_path = " ".join(parts)
    return any(re.search(p, full_path, re.I) for p in EXTRAS_PATTERNS)


def is_episode(path: Path) -> bool:
    return any(re.search(p, path.stem, re.I) for p in EPISODE_PATTERNS)


def detect_mode(path: Path) -> ResolveMode:
    """Auto-detect movie vs series based on path patterns."""
    if path.is_file():
        return ResolveMode.SERIES if is_episode(path) else ResolveMode.MOVIE

    if any(re.search(p, path.name, re.I) for p in EPISODE_PATTERNS):
        return ResolveMode.SERIES

    try:
        for f in path.rglob("*"):
            if f.is_file() and is_video_extension(f) and is_episode(f):
                return ResolveMode.SERIES
    except PermissionError:
        pass

    return ResolveMode.MOVIE


class FolderResolver:
    """Resolves content path to video files (movie/series modes)."""

    def __init__(self, max_files: int = 50):
        self.max_files = max_files

    def resolve(self, content_path: str, mode: ResolveMode = ResolveMode.AUTO) -> ResolveResult:
        path = Path(content_path)
        skipped = []

        if not path.exists():
            return ResolveResult([], mode, [{"file": content_path, "reason": "not_found"}])

        mode = detect_mode(path) if mode == ResolveMode.AUTO else mode

        video_files = [path] if path.is_file() and is_video_extension(path) else list(self._find_videos(path, skipped))

        filtered = []
        for vf in video_files:
            if is_partial_file(vf):
                skipped.append({"file": str(vf), "reason": "partial"})
            elif is_extras_file(vf):
                skipped.append({"file": str(vf), "reason": "extras"})
            elif vf.stat().st_size < MIN_FILE_SIZE:
                skipped.append({"file": str(vf), "reason": "too_small"})
            else:
                filtered.append(vf)

        result = self._select_files(filtered, mode)

        if len(result) > self.max_files:
            for vf in result[self.max_files:]:
                skipped.append({"file": str(vf), "reason": "max_files_exceeded"})
            result = result[:self.max_files]

        return ResolveResult([str(f) for f in result], mode, skipped)

    def _find_videos(self, directory: Path, skipped: list) -> list[Path]:
        try:
            return [f for f in directory.rglob("*") if f.is_file() and is_video_extension(f)]
        except PermissionError:
            skipped.append({"file": str(directory), "reason": "permission_denied"})
            return []

    def _select_files(self, files: list[Path], mode: ResolveMode) -> list[Path]:
        if not files:
            return []

        if mode == ResolveMode.MOVIE:
            return [max(files, key=lambda f: f.stat().st_size)]

        episodes = [f for f in files if is_episode(f)]
        return sorted(episodes or files, key=lambda f: f.name)


def get_folder_resolver() -> FolderResolver:
    from .config import get_config
    return FolderResolver(get_config().max_files_per_enqueue)
