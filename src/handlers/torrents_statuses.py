import logging
from math import floor

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.config import QBT_CREDENTIALS
from bot.constants import STATUS_COMMAND
from services.qbt_services import get_client
from services.qbt_services.qbt_status import torrents_info
from utilities.common import truncate_string

router = Router(name=__name__)
logger = logging.getLogger(__name__)

# Constants
REFRESH_ALL_BUTTON_DATA = "refresh-all"


def format_progress_bar(progress: float) -> str:
    filled = floor(progress * 10)
    return f"[{'■' * filled + '□' * (10 - filled)}]"


def format_status_message(torrent):
    """Formats the status message for a single torrent."""
    return f"{truncate_string(torrent.name, 25)} | {format_progress_bar(torrent.progress)} {torrent.progress * 100:.1f}%"


async def get_torrents() -> list:
    """Retrieves the list of torrents from qBittorrent."""
    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            return await torrents_info(qbt_client, sort="added_on")
    except Exception as e:
        logger.error("Error in getting torrents: %s", e, exc_info=True)
        return []


def get_inline_keyboard(torrents):
    """Creates an inline keyboard with a button for each torrent."""
    buttons = [
        [InlineKeyboardButton(text=format_status_message(torrent), callback_data=f"torrent-{torrent.hash}")]
        for torrent in torrents
    ]
    buttons.append([InlineKeyboardButton(text="Refresh All", callback_data=REFRESH_ALL_BUTTON_DATA)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_status_message(message: Message):
    """Sends the current status message in response to a user's command."""
    torrents = await get_torrents()
    keyboard = get_inline_keyboard(torrents)
    await message.answer("Select a torrent:", reply_markup=keyboard)


async def refresh_status_message(callback_query: CallbackQuery):
    """Sends the current status message in response to a user's command."""
    torrents = await get_torrents()
    keyboard = get_inline_keyboard(torrents)
    try:
        await callback_query.message.edit_text("Select a torrent:", reply_markup=keyboard)
    except TelegramBadRequest:
        await callback_query.answer("Status hasn't changed.")


@router.message(Command(STATUS_COMMAND))
async def handle_status_command(message: Message):
    """Handles the status command from a user."""
    await send_status_message(message)


@router.callback_query(lambda c: c.data and c.data == REFRESH_ALL_BUTTON_DATA)
async def refresh_all_status(callback_query: CallbackQuery):
    """Handles the 'Refresh All' action for the status message."""

    await refresh_status_message(callback_query)


@router.callback_query(lambda c: c.data and c.data.startswith("torrent-"))
async def handle_torrent_button(callback_query: CallbackQuery):
    torrent_hash = callback_query.data.split("-")[1]  # Extract the torrent hash from the callback data
    # Here you would handle the specific action for the torrent. For example:
    # Show detailed status, start/stop, etc.
    # For this example, we'll just log the hash.
    logger.info(f"Torrent selected: {torrent_hash}")
    # You would then update the message or respond appropriately
    await callback_query.answer(f"You selected torrent with hash: {torrent_hash}")
