import logging
from math import floor

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from bot.config import QBT_CREDENTIALS
from bot.constants import STATUS_COMMAND, REFRESH_CALLBACK, TORRENT_DETAILED_CALLBACK
from services.qbt_services import get_client
from services.qbt_services.qbt_status import torrents_info
from utilities.handlers_utils import (redis_callback_get,
                                      redis_callback_save, check_action)
from utilities.common import truncate_string

router = Router(name=__name__)
logger = logging.getLogger(__name__)


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
    buttons = []
    for torrent in torrents:
        callback_data = redis_callback_save({"action": TORRENT_DETAILED_CALLBACK,
                                             "torrent_hash": torrent.hash})
        buttons.append([InlineKeyboardButton(text=format_status_message(torrent),
                                             callback_data=callback_data)])

    buttons.append([InlineKeyboardButton(text="Refresh All", callback_data=REFRESH_CALLBACK)])
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
        logger.info("Status hasn't changed.")
        await callback_query.answer("Status hasn't changed.")


@router.message(Command(STATUS_COMMAND))
async def handle_status_command(message: Message):
    """Handles the status command from a user."""
    await send_status_message(message)


@router.callback_query(lambda c: c.data and c.data == REFRESH_CALLBACK)
async def refresh_all_status(callback_query: CallbackQuery):
    """Handles the 'Refresh All' action for the status message."""

    await refresh_status_message(callback_query)


@router.callback_query(lambda c: check_action(c.data, TORRENT_DETAILED_CALLBACK))
async def handle_torrent_button(callback_query: CallbackQuery):
    torrent_hash = redis_callback_get(callback_query.data)["torrent_hash"]
    logger.info(f"Torrent selected: {torrent_hash}")
    await callback_query.answer(f"You selected torrent with hash: {torrent_hash}")
