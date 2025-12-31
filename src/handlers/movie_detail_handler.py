import logging
import re

from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.text_decorations import html_decoration
from sulguk import SULGUK_PARSE_MODE

from bot.config import QBT_CREDENTIALS
from bot.constants import (
    MOVIE_DETAILED_CALLBACK,
    DOWNLOAD_TORRENT_CALLBACK,
    SEARCH_MOVIE_CALLBACK,
)
from models.movie_detail_service_types import MovieDetails, MovieSearchResult
from torrents import get_torrent_provider
from services.qbt_services import qbt_get_categories, get_client
from utilities import handlers_utils
from utilities.handlers_utils import check_action
from utilities.media_utils import parse_video_quality
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
        # Extract provider_name from movie_details if it's a MovieSearchResult
        provider_name = None
        if isinstance(movie_details, MovieSearchResult) and movie_details.provider_name:
            provider_name = movie_details.provider_name
        
        await send_movie_details(
            callback_query,
            movie_details,
            movie_id,
            results_cache_key,
            tmdb_info=tmdb_info,
            provider_name=provider_name,
        )
    except Exception as e:
        logger.error(f"Error in fetching movie details: {e}", exc_info=True)
        await callback_query.message.answer("Failed to retrieve movie details.")
        await callback_query.answer()


async def _get_movie_details(callback_data: dict, movie_id: str) -> MovieDetails:
    """Retrieve movie details from cache or fetch from provider."""
    provider_name = callback_data.get("provider_name")
    
    if movie_details_data := callback_data.get("movie_details"):
        try:
            logger.info("Using cached movie details for movie ID: %s", movie_id)
            result = MovieSearchResult.model_validate(movie_details_data)
            # Use provider_name from cached data if available
            if result.provider_name:
                provider_name = result.provider_name
            return result
        except ValidationError as exc:
            logger.warning(
                "Failed to use cached movie details for ID %s: %s. Refetching.",
                movie_id,
                exc,
            )
    
    # Get provider by name if specified, otherwise use default
    if provider_name:
        provider = get_torrent_provider(provider_name)
    else:
        provider = torrent_provider
    
    logger.info("Fetching movie details for movie ID: %s from provider: %s", movie_id, provider.name)
    return await provider.get_movie_detail(movie_id)


async def send_movie_details(
    callback_query: CallbackQuery,
    movie_details: MovieDetails,
    movie_id: int | str,
    results_cache_key: str | None,
    tmdb_info: dict | None = None,
    provider_name: str | None = None,
) -> None:
    """Send formatted movie details with download buttons."""
    message_caption = format_movie_details_message(movie_details)
    logger.debug(f"Sending movie details: {message_caption}")

    # Fallback: if tmdb_info is missing, create from torrent provider movie details
    if not tmdb_info:
        logger.info("No tmdb_info provided, using torrent provider movie details as fallback")
        tmdb_info = _create_fallback_tmdb_info(movie_details)
        logger.info("Fallback tmdb_info: %s", tmdb_info)

    qbt_client = await get_client(**QBT_CREDENTIALS)
    categories = await qbt_get_categories(qbt_client)

    reply_markup = create_reply_markup(
        movie_id,
        movie_details.name,
        categories,
        results_cache_key,
        tmdb_info=tmdb_info,
        provider_name=provider_name,
    )
    await callback_query.message.edit_text(
        message_caption, parse_mode=SULGUK_PARSE_MODE, reply_markup=reply_markup
    )


def create_reply_markup(
    movie_id: int | str,
    query: str,
    categories: list[str],
    results_cache_key: str | None,
    tmdb_info: dict | None = None,
    provider_name: str | None = None,
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
                "provider_name": provider_name,
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
    
    # Get provider to generate tracker URL dynamically
    provider = get_torrent_provider(provider_name)
    tracker_url = provider.get_torrent_url(movie_id)
    tracker_button = InlineKeyboardButton(
        text=f"Открыть в {provider.name.capitalize()}",
        url=tracker_url,
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            download_buttons,
            [back_button],
            [tracker_button],
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
    )
    
    # If torrent_html_content is available, use it instead of parsed details
    if movie_details.torrent_html_content:
        message = f"<b>Torrent Details</b>:\n{movie_details.torrent_html_content}"
    else:
        # Fallback to parsed torrent_details
        message += f"<b>Torrent Details</b>:\n"
        for detail in movie_details.torrent_details:
            value = detail.value or "-"
            message += f"- {bold(detail.key)} {code(value)}\n"

    return message


def _create_fallback_tmdb_info(movie_details: MovieDetails) -> dict:
    """Create tmdb_info from torrent provider movie details as fallback.
    
    Torrent provider names are usually in format:
    - "Русское название / English Title (сезон...) / 2024 / ..."
    - "Русское название / English Title / 2024 / ..."
    """
    name = movie_details.name
    year = movie_details.year
    quality = movie_details.video_quality
    
    # Try to extract English title (after " / ")
    original_title = None
    if " / " in name:
        parts = name.split(" / ")
        # Usually: [Russian, English, Year/Info, ...]
        # English title is often the second part
        if len(parts) >= 2:
            # Check if second part looks like English (contains ASCII letters)
            candidate = parts[1].strip()
            # Remove season info like "(1 сезон...)"
            candidate = re.sub(r'\s*\([^)]*сезон[^)]*\)', '', candidate)
            candidate = re.sub(r'\s*\([^)]*season[^)]*\)', '', candidate, flags=re.IGNORECASE)
            candidate = candidate.strip()
            
            if candidate and re.search(r'[a-zA-Z]', candidate):
                original_title = candidate
    
    # If no English title found, use the full name
    if not original_title:
        # Clean up the name - take first part before "/"
        original_title = name.split(" / ")[0].strip() if " / " in name else name
        # Remove season/episode info
        original_title = re.sub(r'\s*\([^)]*сезон[^)]*\)', '', original_title)
        original_title = re.sub(r'\s*\([^)]*серии[^)]*\)', '', original_title)
        original_title = original_title.strip()
    
    # Parse quality from name if not in movie_details
    if not quality:
        quality = parse_video_quality(name)
    
    # Parse year - it might be a string like "2024" or range "1999-2004"
    parsed_year = None
    if year:
        # Extract first year from string
        year_match = re.search(r'(\d{4})', str(year))
        if year_match:
            parsed_year = int(year_match.group(1))
    
    return {
        "original_title": original_title,
        "year": parsed_year,
        "quality": quality,
    }
