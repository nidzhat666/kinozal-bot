import logging
from aiogram import Router
from aiogram.types import CallbackQuery

from bot.constants import TORRENT_DEFAULT_CATEGORY
from handlers.torrents_statuses import handle_status_command
from utilities.handlers_utils import redis_callback_get
from services.kinozal_services.movie_download_service import MovieDownloadService
from services.kinozal_services.kinozal_auth_service import KinozalAuthService
from services.qbt_services import get_client, add_torrent
from bot.config import KINOZAL_CREDENTIALS, QBT_CREDENTIALS

router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.callback_query(
    lambda c: c.data and redis_callback_get(c.data).get("action") == "download_movie"
)
async def handle_movie_download(callback_query: CallbackQuery):
    movie_id = callback_query.data.split("_")[1]
    category = callback_query.data.split("_")[2]
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
        auth_service = KinozalAuthService(**KINOZAL_CREDENTIALS)
        movie_download_service = MovieDownloadService(movie_id, await auth_service.authenticate())
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
