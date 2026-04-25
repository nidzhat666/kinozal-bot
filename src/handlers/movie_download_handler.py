from time import perf_counter

from aiogram import Router
from aiogram.types import CallbackQuery

from bot.config import QBT_CREDENTIALS
from bot.constants import DOWNLOAD_TORRENT_CALLBACK, TORRENT_DEFAULT_CATEGORY
from handlers.torrents_statuses_handler import handle_status_command
from services.qbt_services import get_client
from services.qbt_services.qbt_add_and_rename import add_torrent_and_rename
from torrents import get_registered_providers, get_torrent_provider
from torrents.interfaces import DownloadResult
from utilities.handlers_utils import check_action, redis_callback_get
from utilities.logger_utils import get_handler_logger

router = Router(name=__name__)
logger = get_handler_logger("movie_download")


@router.callback_query(lambda c: check_action(c.data, DOWNLOAD_TORRENT_CALLBACK))
async def handle_movie_download(callback_query: CallbackQuery):
    """Handle torrent download and add to qBittorrent."""
    started_at = perf_counter()
    user_id = callback_query.from_user.id if callback_query.from_user else None
    handler_logger = logger.bind(user_id=user_id)

    callback_data = redis_callback_get(callback_query.data)
    movie_id = callback_data.get("movie_id")
    category = callback_data.get("category")
    tmdb_info = callback_data.get("tmdb_info")
    provider_name = callback_data.get("provider_name")

    if not provider_name:
        error_type = "ValidationError"
        error_msg = (
            f"Provider name is required for download. Movie ID: {movie_id}. "
            f"Available providers: {', '.join(get_registered_providers())}"
        )
        handler_logger.error(
            "Provider name missing",
            movie_id=movie_id,
            error_type=error_type,
            error_message=error_msg,
        )
        await callback_query.answer(error_msg, show_alert=True)
        return

    handler_logger.info(
        "Handling download request",
        movie_id=movie_id,
        provider=provider_name,
    )

    try:
        download_result = await _download_torrent(movie_id, provider_name, handler_logger)
        await _add_to_qbittorrent(download_result, category, tmdb_info, handler_logger)

        await callback_query.message.delete_reply_markup()
        await handle_status_command(callback_query.message)
        duration_ms = int((perf_counter() - started_at) * 1000)
        handler_logger.info(
            "Movie successfully added to qBittorrent",
            movie_id=movie_id,
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((perf_counter() - started_at) * 1000)
        error_type = type(e).__name__
        handler_logger.error(
            "Error handling download",
            movie_id=movie_id,
            error_type=error_type,
            error_message=str(e),
            duration_ms=duration_ms,
            exc_info=True,
        )
        await callback_query.answer(f"Failed to add torrent: {e}")


async def _download_torrent(movie_id: str, provider_name: str, handler_logger) -> DownloadResult:
    """Download torrent file from provider."""
    if not provider_name:
        raise ValueError(f"Provider name is required for download. Movie ID: {movie_id}")

    provider = get_torrent_provider(provider_name)
    handler_logger.info(
        "Using provider for download",
        provider=provider_name,
        movie_id=movie_id,
    )

    file_info = await provider.download_movie(movie_id)
    handler_logger.info(
        "Downloaded movie",
        movie_id=movie_id,
        file_path=file_info.file_path,
    )
    return file_info


async def _add_to_qbittorrent(
    download_result: DownloadResult,
    category: str | None,
    tmdb_info: dict | None,
    handler_logger,
) -> None:
    """Add torrent to qBittorrent with optional auto-rename."""
    handler_logger.info("tmdb_info received", tmdb_info=tmdb_info)

    async with await get_client(**QBT_CREDENTIALS) as qbt_client:
        original_title = tmdb_info.get("original_title") if tmdb_info else None
        year = tmdb_info.get("year") if tmdb_info else None
        quality = tmdb_info.get("quality") if tmdb_info else None
        season = tmdb_info.get("season") if tmdb_info else None

        await add_torrent_and_rename(
            download_result.file_path,
            qbt_client,
            category or TORRENT_DEFAULT_CATEGORY,
            original_title=original_title,
            year=year,
            quality=quality,
            season=season,
        )
        handler_logger.info(
            "Torrent added",
            file_path=download_result.file_path,
        )
