import logging
from aiogram import Router
from aiogram.types import CallbackQuery

from bot.constants import TORRENT_DEFAULT_CATEGORY, DOWNLOAD_TORRENT_CALLBACK
from handlers.torrents_statuses_handler import handle_status_command
from utilities.handlers_utils import redis_callback_get, check_action
from torrents import get_torrent_provider
from services.qbt_services import get_client, add_torrent
from bot.config import QBT_CREDENTIALS
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


async def download_movie(movie_id: str) -> dict[str, str]:
    try:
        auth_service = torrent_provider.get_auth_service()
        if auth_service is None:
            raise RuntimeError("Selected torrent provider does not support authenticated downloads.")
        auth_data = await auth_service.authenticate()
        movie_download_service = torrent_provider.get_download_service(movie_id, auth_data)
        file_info = await movie_download_service.download_movie()
        logger.info(f"Downloaded movie with ID {movie_id} to path: {file_info}")
        return file_info
    except Exception as e:
        logger.error(f"Error downloading movie with ID {movie_id}: {e}", exc_info=True)
        raise


async def add_movie_to_qbt(file_path: dict[str, str],
                           category: str = TORRENT_DEFAULT_CATEGORY):
    try:
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            await add_torrent(file_path, qbt_client, category)
            logger.info(f"Torrent added to qBittorrent for file: {file_path}")
    except Exception as e:
        logger.error(f"Error adding torrent to qBittorrent for file {file_path}: {e}", exc_info=True)
        raise
