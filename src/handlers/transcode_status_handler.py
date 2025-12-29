"""
Telegram handler for transcoding status.

Provides /transcode_status command to view:
- Worker statuses (idle/working, progress)
- Queue statistics
- Recent completed/failed jobs
- Aggregate statistics
"""

import logging
import time
from math import floor

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.constants import TRANSCODE_STATUS_COMMAND, TRANSCODE_REFRESH_CALLBACK
from services.transcoding.config import get_config
from services.transcoding.models import WorkerState
from services.transcoding.worker_pool import get_worker_pool
from services.transcoding.history import get_history_service

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def format_progress_bar(progress: float) -> str:
    """Format progress as visual bar."""
    filled = floor(progress / 10)
    return f"[{'■' * filled}{'□' * (10 - filled)}]"


def format_time_ago(timestamp: float | None) -> str:
    """Format timestamp as 'X ago' string."""
    if timestamp is None:
        return "never"

    diff = time.time() - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        minutes = int(diff / 60)
        return f"{minutes}m ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours}h ago"
    else:
        days = int(diff / 86400)
        return f"{days}d ago"


def format_bytes(bytes_count: int) -> str:
    """Format bytes as human-readable string."""
    if bytes_count >= 1024 ** 4:
        return f"{bytes_count / (1024 ** 4):.1f} TB"
    elif bytes_count >= 1024 ** 3:
        return f"{bytes_count / (1024 ** 3):.1f} GB"
    elif bytes_count >= 1024 ** 2:
        return f"{bytes_count / (1024 ** 2):.1f} MB"
    elif bytes_count >= 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count} B"


def truncate_filename(filename: str, max_length: int = 25) -> str:
    """Truncate filename to max length."""
    if len(filename) <= max_length:
        return filename
    return filename[:max_length - 3] + "..."


async def build_status_message() -> str:
    """Build the full status message."""
    config = get_config()
    lines = ["📊 <b>Transcoding Status</b>\n"]

    # Check if enabled
    if not config.enabled:
        lines.append("⚠️ Transcoding is <b>disabled</b>")
        return "\n".join(lines)

    # Get worker pool status
    pool = get_worker_pool()
    pool_status = await pool.get_status()

    # Workers section
    lines.append("<b>Workers:</b>")
    for worker in pool_status.workers:
        if worker.state == WorkerState.WORKING:
            emoji = "🟢"
            filename = truncate_filename(worker.current_file or "unknown")
            progress = f"{worker.progress:.1f}%"
            eta_str = f", ETA {worker.eta}" if worker.eta else ""
            speed_str = f" ({worker.speed})" if worker.speed else ""
            lines.append(f"{emoji} Worker {worker.worker_id}: {filename}")
            lines.append(f"   {format_progress_bar(worker.progress)} {progress}{eta_str}{speed_str}")
        elif worker.state == WorkerState.STOPPING:
            emoji = "🟡"
            lines.append(f"{emoji} Worker {worker.worker_id}: stopping")
        else:
            emoji = "⚪"
            lines.append(f"{emoji} Worker {worker.worker_id}: idle")

    lines.append("")

    # Queue section
    queue = pool_status.queue_stats
    lines.append(f"<b>Queue:</b> {queue.total} tasks")
    if queue.total > 0:
        lines.append(f"   📥 High priority: {queue.high_priority}")
        lines.append(f"   📦 Low priority: {queue.low_priority}")
    lines.append(f"   ⚙️ Processing: {queue.processing}")
    lines.append("")

    # Get history and stats
    history = await get_history_service()
    recent = await history.get_recent_history(success_count=5, failed_count=3)
    stats = recent.stats

    # Stats section
    lines.append("<b>Stats:</b>")
    lines.append(f"✅ Completed: {stats.total_success} files ({format_bytes(stats.total_bytes_processed)})")
    if stats.last_success_at:
        lines.append(f"   Last: {format_time_ago(stats.last_success_at)}")

    if stats.total_failed > 0:
        lines.append(f"❌ Failed: {stats.total_failed}")
        if stats.last_failed_at:
            lines.append(f"   Last: {format_time_ago(stats.last_failed_at)}")

    # Recent completed
    if recent.success:
        lines.append("")
        lines.append("<b>Recent completed:</b>")
        for job in recent.success[:5]:
            lines.append(f"• {truncate_filename(job.filename, 30)}")

    # Recent failed
    if recent.failed:
        lines.append("")
        lines.append("<b>Recent failed:</b>")
        for job in recent.failed[:3]:
            error = job.error_message[:30] if job.error_message else "unknown error"
            lines.append(f"• {truncate_filename(job.filename, 20)}: {error}")

    return "\n".join(lines)


def get_refresh_keyboard() -> InlineKeyboardMarkup:
    """Create refresh button keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data=TRANSCODE_REFRESH_CALLBACK)]
        ]
    )


@router.message(Command(TRANSCODE_STATUS_COMMAND))
async def handle_transcode_status_command(message: Message) -> None:
    """Handle /transcode_status command."""
    try:
        status_text = await build_status_message()
        await message.answer(
            status_text,
            reply_markup=get_refresh_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Error getting transcode status: {e}", exc_info=True)
        await message.answer("❌ Error getting transcoding status")


@router.callback_query(lambda c: c.data == TRANSCODE_REFRESH_CALLBACK)
async def handle_transcode_refresh(callback_query: CallbackQuery) -> None:
    """Handle refresh button click."""
    try:
        status_text = await build_status_message()
        await callback_query.message.edit_text(
            status_text,
            reply_markup=get_refresh_keyboard(),
            parse_mode="HTML",
        )
        await callback_query.answer("Status refreshed")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback_query.answer("Status hasn't changed")
        else:
            logger.error(f"Error refreshing transcode status: {e}")
            await callback_query.answer("Error refreshing status")
    except Exception as e:
        logger.error(f"Error refreshing transcode status: {e}", exc_info=True)
        await callback_query.answer("Error refreshing status")

