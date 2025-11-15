import logging
from aiogram import Router
from aiogram.types import CallbackQuery

from bot.constants import TORRENT_DEFAULT_CATEGORY, DOWNLOAD_TORRENT_CALLBACK
from handlers.torrents_statuses_handler import handle_status_command
from utilities.handlers_utils import redis_callback_get, check_action
from torrents import get_torrent_provider
from services.qbt_services import get_client, add_torrent
from bot.config import QBT_CREDENTIALS
from torrents.interfaces import DownloadResult

torrent_provider = get_torrent_provider()


router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.callback_query(lambda c: check_action(c.data, DOWNLOAD_TORRENT_CALLBACK))
async def handle_movie_download(callback_query: CallbackQuery):
    callback_data = redis_callback_get(callback_query.data)
    movie_id = callback_data.get("movie_id")
    category = callback_data.get("category")
    logger.info(f"Handling download request for movie ID: {movie_id}")

    try:
        file_path = await download_movie(movie_id)
        await add_movie_to_qbt(file_path, category)
        await callback_query.message.delete_reply_markup()
        await handle_status_command(callback_query.message)
        logger.info("Movie successfully added to qBittorrent.")
    except Exception as e:
        logger.error(f"Error in handling movie download for ID {movie_id}: {e}", exc_info=True)
        await callback_query.answer(f"Failed to add torrent to download queue: {e}")


async def download_movie(movie_id: str) -> DownloadResult:
    try:
        file_info = await torrent_provider.download_movie(movie_id)
        logger.info(f"Downloaded movie with ID {movie_id} to path: {file_info.file_path}")
        return file_info
    except Exception as e:
        logger.error(f"Error downloading movie with ID {movie_id}: {e}", exc_info=True)
        raise


async def add_movie_to_qbt(download_result: DownloadResult,
                           category: str = TORRENT_DEFAULT_CATEGORY):
    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            await add_torrent(download_result.file_path, qbt_client, category)
            logger.info(f"Torrent added to qBittorrent for file: {download_result.file_path}")
    except Exception as e:
        logger.error(f"Error adding torrent to qBittorrent for file {download_result.file_path}: {e}", exc_info=True)
        raise
