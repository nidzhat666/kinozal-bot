import re
from datetime import datetime


def format_size(size_in_bytes: int) -> str:
    """Convert bytes to human-readable format (B, KB, MB, GB, TB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024
    return f"{size_in_bytes:.2f} TB"


def format_percentage(value: float) -> str:
    """Convert decimal fraction (0.0-1.0) to percentage string."""
    return f"{value * 100:.2f}%"


def format_speed(speed_in_bytes_per_second: int) -> str:
    """Convert bytes/second to human-readable format."""
    return f"{format_size(speed_in_bytes_per_second)}/s"


def format_date(dt: datetime | None) -> str:
    """Format datetime to YYYY-MM-DD HH:MM:SS or 'N/A' if None."""
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"


def format_eta(eta: float) -> str:
    """Convert ETA in seconds to human-readable format (e.g., '2h 15m 30s left')."""
    if eta < 0 or eta >= 31536000:  # 365 days in seconds
        return "∞"
    hours, remainder = divmod(int(eta), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s left"


def sanitize_fs_name(name: str, max_length: int = 180) -> str:
    """Sanitize string for use as filesystem name (removes invalid chars, limits length)."""
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(".")
    
    if len(name) > max_length:
        name = name[:max_length].strip()
        
    return name
