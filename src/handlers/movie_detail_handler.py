import logging

from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.text_decorations import html_decoration

from bot.config import QBT_CREDENTIALS
from bot.constants import (
    MOVIE_DETAILED_CALLBACK,
    DOWNLOAD_TORRENT_CALLBACK,
    SEARCH_MOVIE_CALLBACK,
)
from models.movie_detail_service_types import MovieDetails, MovieSearchResult
from torrents import get_torrent_provider
from services.qbt_services import qbt_get_categories, get_client
from utilities import kinozal_utils, handlers_utils
from utilities.handlers_utils import check_action
from pydantic import ValidationError

logger = logging.getLogger(__name__)
router = Router(name=__name__)

torrent_provider = get_torrent_provider()


@router.callback_query(lambda c: check_action(c.data, MOVIE_DETAILED_CALLBACK))
async def handle_movie_selection(callback_query: CallbackQuery):
    """Handle torrent selection and display detailed information."""
    callback_data = handlers_utils.redis_callback_get(callback_query.data)
    movie_id = callback_data.get("movie_id")
    results_cache_key = callback_data.get("results_cache_key")
    tmdb_info = callback_data.get("tmdb_info")
    
    logger.info(f"Movie selected with ID: {movie_id}")

    try:
        movie_details = await _get_movie_details(callback_data, movie_id)
        await send_movie_details(
            callback_query,
            movie_details,
            movie_id,
            results_cache_key,
            tmdb_info=tmdb_info,
        )
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


async def _get_movie_details(callback_data: dict, movie_id: str) -> MovieDetails:
    """Retrieve movie details from cache or fetch from provider."""
    if movie_details_data := callback_data.get("movie_details"):
        try:
            logger.info("Using cached movie details for movie ID: %s", movie_id)
            return MovieSearchResult.model_validate(movie_details_data)
        except ValidationError as exc:
            logger.warning(
                "Failed to use cached movie details for ID %s: %s. Refetching.",
                movie_id,
                exc,
            )
    
    logger.info("Fetching movie details for movie ID: %s", movie_id)
    return await torrent_provider.get_movie_detail(movie_id)


async def send_movie_details(
    callback_query: CallbackQuery,
    movie_details: MovieDetails,
    movie_id: int | str,
    results_cache_key: str | None,
    tmdb_info: dict | None = None,
) -> None:
    """Send formatted movie details with download buttons."""
    message_caption = format_movie_details_message(movie_details)
    logger.debug(f"Sending movie details: {message_caption}")

    qbt_client = await get_client(**QBT_CREDENTIALS)
    categories = await qbt_get_categories(qbt_client)

    reply_markup = create_reply_markup(
        movie_id,
        movie_details.name,
        categories,
        results_cache_key,
        tmdb_info=tmdb_info,
    )
    await callback_query.message.edit_text(
        message_caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup
    )


def create_reply_markup(
    movie_id: int | str,
    query: str,
    categories: list[str],
    results_cache_key: str | None,
    tmdb_info: dict | None = None,
) -> InlineKeyboardMarkup:
    """Create inline keyboard with download buttons and navigation."""
    download_buttons = [
        InlineKeyboardButton(
            text=f"{category} 🔽",
            callback_data=handlers_utils.redis_callback_save({
                "action": DOWNLOAD_TORRENT_CALLBACK,
                "movie_id": movie_id,
                "category": category,
                "query": query,
                "tmdb_info": tmdb_info,
            }),
        )
        for category in categories
    ]

    back_button = InlineKeyboardButton(
        text="Назад к результатам поиска",
        callback_data=handlers_utils.redis_callback_save({
            "action": SEARCH_MOVIE_CALLBACK,
            "results_cache_key": results_cache_key,
        }),
    )
    
    kinozal_button = InlineKeyboardButton(
        text="Открыть в Кинозале",
        url=kinozal_utils.get_url(f"/details.php?id={movie_id}"),
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            download_buttons,
            [back_button],
            [kinozal_button],
        ]
    )


def format_movie_details_message(movie_details: MovieDetails) -> str:
    """Format movie details into HTML message."""
    bold = html_decoration.bold
    code = html_decoration.code
    
    message = (
        f"{bold('Название')}: {movie_details.name}\n"
        f"{bold('Год')}: {movie_details.year}\n"
        f"{bold('Жанр')}: {', '.join(movie_details.genres)}\n"
        f"{bold('Режисер')}: {movie_details.director}\n"
        f"{bold('Актеры')}: {', '.join(movie_details.actors[:5])}\n\n"
        f"{bold('Рейтинги')}:\n"
        f"- IMDB: {code(movie_details.ratings.imdb)}\n"
        f"- Kinopoisk: {code(movie_details.ratings.kinopoisk)}\n\n"
        f"<b>Torrent Details</b>:\n"
    )
    
    for detail in movie_details.torrent_details:
        value = detail.value or "-"
        message += f"- {bold(detail.key)} {code(value)}\n"

    return message
