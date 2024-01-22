import asyncio
import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from bot.config import QBT_CREDENTIALS
from bot.constants import TORRENT_DELETE_CALLBACK
from handlers.torrents_statuses_handler import refresh_all_status
from services.qbt_services import get_client
from services.qbt_services.qbt_torrent_pause_start_delete import delete_torrent
from utilities.handlers_utils import check_action, redis_callback_get

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(lambda c: check_action(c.data, TORRENT_DELETE_CALLBACK))
async def handle_torrent_delete(callback_query: CallbackQuery):
    """
    Handles the delete button for a torrent.

    :param callback_query: CallbackQuery object.
    """
    torrent_hash = redis_callback_get(callback_query.data).get("torrent_hash")
    logger.info(f"Delete torrent {torrent_hash}")
    if not torrent_hash:
        await callback_query.answer("Torrent hash not found.")
        return
    async with await get_client(**QBT_CREDENTIALS) as qbt_client:
        try:
            await delete_torrent(qbt_client, torrent_hash)
            await callback_query.answer("Torrent deleted.")
            await asyncio.sleep(3)
            await refresh_all_status(callback_query)
        except Exception as e:
            logger.error(f"Error in delete torrent: {e}", exc_info=True)
            await callback_query.answer("Failed to delete torrent.")
            return
