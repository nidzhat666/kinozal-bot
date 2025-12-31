import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from bot.config import QBT_CREDENTIALS
from bot.constants import DOWNLOAD_TORRENT_CALLBACK, TORRENT_DEFAULT_CATEGORY
from handlers.torrents_statuses_handler import handle_status_command
from services.qbt_services import get_client
from services.qbt_services.qbt_add_and_rename import add_torrent_and_rename
from torrents import get_torrent_provider, get_registered_providers
from torrents.interfaces import DownloadResult
from utilities.handlers_utils import check_action, redis_callback_get

router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.callback_query(lambda c: check_action(c.data, DOWNLOAD_TORRENT_CALLBACK))
async def handle_movie_download(callback_query: CallbackQuery):
    """Handle torrent download and add to qBittorrent."""
    callback_data = redis_callback_get(callback_query.data)
    movie_id = callback_data.get("movie_id")
    category = callback_data.get("category")
    tmdb_info = callback_data.get("tmdb_info")
    provider_name = callback_data.get("provider_name")
    
    if not provider_name:
        error_msg = (
            f"Provider name is required for download. Movie ID: {movie_id}. "
            f"Available providers: {', '.join(get_registered_providers())}"
        )
        logger.error(error_msg)
        await callback_query.answer(error_msg, show_alert=True)
        return
    
    logger.info(f"Handling download request for movie ID: {movie_id}, provider: {provider_name}")

    try:
        download_result = await _download_torrent(movie_id, provider_name)
        await _add_to_qbittorrent(download_result, category, tmdb_info)
        
        await callback_query.message.delete_reply_markup()
        await handle_status_command(callback_query.message)
        logger.info("Movie successfully added to qBittorrent.")
    except Exception as e:
        logger.error(f"Error handling download for ID {movie_id}: {e}", exc_info=True)
        await callback_query.answer(f"Failed to add torrent: {e}")


async def _download_torrent(movie_id: str, provider_name: str) -> DownloadResult:
    """Download torrent file from provider.
    
    Args:
        movie_id: Movie ID on the tracker.
        provider_name: Provider name (required, no default).
        
    Raises:
        ValueError: If provider_name is not provided.
        KeyError: If provider is not found.
    """
    if not provider_name:
        raise ValueError(
            f"Provider name is required for download. Movie ID: {movie_id}"
        )
    
    provider = get_torrent_provider(provider_name)
    logger.info(f"Using provider '{provider_name}' for download of movie ID: {movie_id}")
    
    file_info = await provider.download_movie(movie_id)
    logger.info(f"Downloaded movie {movie_id} to: {file_info.file_path}")
    return file_info


async def _add_to_qbittorrent(
    download_result: DownloadResult,
    category: str = TORRENT_DEFAULT_CATEGORY,
    tmdb_info: dict | None = None,
) -> None:
    """Add torrent to qBittorrent with optional auto-rename."""
    logger.info("tmdb_info received: %s", tmdb_info)
    
    async with await get_client(**QBT_CREDENTIALS) as qbt_client:
        original_title = tmdb_info.get("original_title") if tmdb_info else None
        year = tmdb_info.get("year") if tmdb_info else None
        quality = tmdb_info.get("quality") if tmdb_info else None
        season = tmdb_info.get("season") if tmdb_info else None

        await add_torrent_and_rename(
            download_result.file_path,
            qbt_client,
            category,
            original_title=original_title,
            year=year,
            quality=quality,
            season=season,
        )
        logger.info(f"Torrent added for file: {download_result.file_path}")
