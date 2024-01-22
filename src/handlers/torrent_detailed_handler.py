import logging

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aioqbt.api import TorrentInfo, TorrentState

from bot.config import QBT_CREDENTIALS
from bot.constants import (TORRENT_DETAILED_CALLBACK, TORRENT_START_CALLBACK,
                           TORRENT_PAUSE_CALLBACK, TORRENT_DELETE_CALLBACK, REFRESH_CALLBACK)
from services.qbt_services import get_client
from services.qbt_services.qbt_torrent_details import get_torrent_details
from utilities.format_utils import format_size, format_percentage, format_speed, format_date, format_eta
from utilities.handlers_utils import check_action, redis_callback_get, redis_callback_save

router = Router(name=__name__)
logger = logging.getLogger(__name__)


def create_detail_message(torrent: TorrentInfo) -> str:
    """
    Formats the torrent details into an HTML message.

    :param torrent: TorrentInfo object containing torrent details.
    :return: Formatted HTML string with torrent details.
    """
    eta = format_eta(torrent.eta.total_seconds())
    return (f"<b>Torrent Details</b>\n"
            f"- <b>Name:</b> {torrent.name}\n"
            f"- <b>Size:</b> {format_size(torrent.size)}\n"
            f"- <b>Progress:</b> {format_percentage(torrent.progress)}\n"
            f"- <b>Download Speed:</b> {format_speed(torrent.dlspeed)}\n"
            f"- <b>Upload Speed:</b> {format_speed(torrent.upspeed)}\n"
            f"- <b>Seeds:</b> {torrent.num_seeds}\n"
            f"- <b>Peers:</b> {torrent.num_leechs}\n"
            f"- <b>Status:</b> {torrent.state}\n"
            f"- <b>Added On:</b> {format_date(torrent.added_on)}\n"
            f"- <b>Completion On:</b> {format_date(torrent.completion_on)}\n"
            f"- <b>Download Path:</b> {torrent.download_path}\n"
            f"- <b>ETA:</b> {eta}\n")


def get_inline_keyboard(torrent_hash: str, is_paused: bool = True,
                        is_downloading: bool = False) -> InlineKeyboardMarkup:
    """
    Creates an inline keyboard with buttons for torrent actions.

    :param is_paused:
    :param is_downloading:
    :param torrent_hash: Unique hash of the torrent.
    :return: InlineKeyboardMarkup object for the torrent.
    """
    action_buttons = [
        InlineKeyboardButton(text="Delete", callback_data=redis_callback_save({"action": TORRENT_DELETE_CALLBACK,
                                                                               "torrent_hash": torrent_hash})),
    ]
    if is_downloading:
        action_buttons += [InlineKeyboardButton(text="Pause", callback_data=redis_callback_save({"action": TORRENT_PAUSE_CALLBACK,
                                                                                                 "torrent_hash": torrent_hash})), ]
    elif is_paused:
        action_buttons += [InlineKeyboardButton(text="Start", callback_data=redis_callback_save({"action": TORRENT_START_CALLBACK,
                                                                                                 "torrent_hash": torrent_hash})), ]

    buttons = [action_buttons,
               [InlineKeyboardButton(text="Refresh", callback_data=redis_callback_save({"action": TORRENT_DETAILED_CALLBACK,
                                                                                        "torrent_hash": torrent_hash})),
                InlineKeyboardButton(text="Back", callback_data=REFRESH_CALLBACK)]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(lambda c: check_action(c.data, TORRENT_DETAILED_CALLBACK))
async def handle_torrent_button(callback_query: CallbackQuery):
    """
    Handles the callback query for a torrent button.

    :param callback_query: CallbackQuery object from the user interaction.
    """
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
                                           reply_markup=get_inline_keyboard(torrent_hash,
                                                                            is_downloading=torrent_details.state in (TorrentState.DOWNLOADING,
                                                                                                                     TorrentState.STALLED_DL),
                                                                            is_paused=torrent_details.state == TorrentState.PAUSED_DL))
