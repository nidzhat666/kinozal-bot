from datetime import datetime


def format_size(size_in_bytes: int) -> str:
    """
    Convert a file size in bytes to a human-readable format.

    :param size_in_bytes: Size in bytes.
    :return: Human-readable file size.
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024
    return f"{size_in_bytes:.2f} TB"


def format_percentage(value: float) -> str:
    """
    Convert a decimal fraction to a percentage string.

    :param value: Decimal fraction.
    :return: Percentage string.
    """
    return f"{value * 100:.2f}%"


def format_speed(speed_in_bytes_per_second: int) -> str:
    """
    Convert speed from bytes per second to a human-readable format.

    :param speed_in_bytes_per_second: Speed in bytes per second.
    :return: Human-readable speed string.
    """
    return format_size(speed_in_bytes_per_second) + "/s"


def format_date(dt: datetime | None) -> str:
    """
    Format a UNIX timestamp into a human-readable date.

    :param dt: datetime object or None.
    :return: Formatted date string or "N/A".
    """
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return "N/A"


def format_eta(eta: float) -> str:
    """
    Converts ETA in seconds to a human-readable format.

    :param eta: Estimated time of arrival in seconds.
    :return: Human-readable ETA.
    """
    if eta < 0 or eta >= 86400 * 365:  # 365 days
        return "∞"
    hours, remainder = divmod(eta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s left"
