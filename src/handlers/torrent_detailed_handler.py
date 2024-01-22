import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aioqbt.api import TorrentInfo

from bot.config import QBT_CREDENTIALS
from bot.constants import (TORRENT_DETAILED_CALLBACK, TORRENT_START_CALLBACK,
                           TORRENT_PAUSE_CALLBACK, TORRENT_DELETE_CALLBACK, REFRESH_CALLBACK, )
from services.qbt_services import get_client
from services.qbt_services.qbt_torrent_details import get_torrent_details
from utilities.handlers_utils import check_action, redis_callback_get, redis_callback_save

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def create_detail_message(torrent: TorrentInfo) -> str:
    """Formats the torrent details into an HTML message."""
    eta = format_eta(torrent.eta.total_seconds())
    return (f"""<b>Torrent Details</b>
- <b>Name:</b> {torrent.name}
- <b>Size:</b> {format_size(torrent.size)}
- <b>Progress:</b> {format_percentage(torrent.progress)}
- <b>Download Speed:</b> {format_speed(torrent.dlspeed)}
- <b>Upload Speed:</b> {format_speed(torrent.upspeed)}
- <b>Seeds:</b> {torrent.num_seeds}
- <b>Peers:</b> {torrent.num_leechs}
- <b>Status:</b> {torrent.state}
- <b>Added On:</b> {format_date(torrent.added_on)}
- <b>Completion On:</b> {format_date(torrent.completion_on)}
- <b>Download Path:</b> {torrent.download_path}
- <b>ETA:</b> {eta}
"""
            )


def format_size(size_in_bytes):
    """Convert a file size in bytes to a human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024
    return f"{size_in_bytes:.2f} TB"


def format_percentage(value):
    """Convert a decimal fraction to a percentage string."""
    return f"{value * 100:.2f}%"


def format_speed(speed_in_bytes_per_second):
    """Convert speed from bytes per second to a human-readable format."""
    return format_size(speed_in_bytes_per_second) + "/s"


def format_date(dt):
    """Format a UNIX timestamp into a human-readable date."""
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return "N/A"


def format_eta(eta: int | float) -> str:
    """Converts ETA in seconds to a human-readable format."""
    if eta < 0 or eta >= 86400 * 365:  # 365 days
        return "∞"
    hours, remainder = divmod(eta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s left"


def get_inline_keyboard(torrent_hash: str, is_completed: bool = True) -> InlineKeyboardMarkup:
    """Creates an inline keyboard with a button for each torrent."""
    action_buttons = [
        InlineKeyboardButton(text="Delete", callback_data=redis_callback_save({"action": TORRENT_DELETE_CALLBACK,
                                                                               "torrent_hash": torrent_hash})),
    ]
    if not is_completed:
        action_buttons.append([
            InlineKeyboardButton(text="Start", callback_data=redis_callback_save({"action": TORRENT_START_CALLBACK,
                                                                                  "torrent_hash": torrent_hash})),
            InlineKeyboardButton(text="Pause", callback_data=redis_callback_save({"action": TORRENT_PAUSE_CALLBACK,
                                                                                  "torrent_hash": torrent_hash})),
        ], )

    buttons = [action_buttons,
               [InlineKeyboardButton(text="Refresh", callback_data=redis_callback_save({"action": TORRENT_DETAILED_CALLBACK,
                                                                                        "torrent_hash": torrent_hash})),
                InlineKeyboardButton(text="Back", callback_data=REFRESH_CALLBACK)], ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(lambda c: check_action(c.data, TORRENT_DETAILED_CALLBACK))
async def handle_torrent_button(callback_query: CallbackQuery):
    """Handles the callback query for a torrent button."""
    callback_data = redis_callback_get(callback_query.data)
    torrent_hash = callback_data.get("torrent_hash")
    if not torrent_hash:
        await callback_query.answer("Torrent hash not found.")
        return

    logger.info(f"Torrent selected: {torrent_hash}")
    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            torrent_details = await get_torrent_details(qbt_client, torrent_hash)
    except Exception as e:
        logger.error(f"Error in getting torrent details: {e}", exc_info=True)
        await callback_query.answer("Failed to retrieve torrent details.")
        return

    if torrent_details is None:
        await callback_query.answer("Torrent not found.")
        return

    message = create_detail_message(torrent_details)
    await callback_query.message.edit_text(message, parse_mode="HTML",
                                           reply_markup=get_inline_keyboard(torrent_hash, is_completed=True if torrent_details.progress == 1 else False))
