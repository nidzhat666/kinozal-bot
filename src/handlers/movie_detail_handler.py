import logging
import re

from aiogram import Router
from aiogram.enums.parse_mode import ParseMode
from aiogram.exceptions import TelegramBadRequest
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
    
    # Extract provider_name from callback_data first (most reliable source)
    provider_name = callback_data.get("provider_name")
    
    # Also try to get it from cached movie_details if available
    if not provider_name and (movie_details_data := callback_data.get("movie_details")):
        try:
            result = MovieSearchResult.model_validate(movie_details_data)
            if result.provider_name:
                provider_name = result.provider_name
                logger.debug(
                    "Extracted provider_name '%s' from cached movie_details for movie ID: %s",
                    provider_name,
                    movie_id
                )
        except Exception as exc:
            logger.debug(
                "Could not extract provider_name from cached movie_details: %s",
                exc
            )
    
    logger.info(
        "Movie selected with ID: %s, provider: %s",
        movie_id,
        provider_name or "default"
    )

    try:
        movie_details = await _get_movie_details(callback_data, movie_id)
        
        # If provider_name still not set, try to get it from movie_details
        if not provider_name and isinstance(movie_details, MovieSearchResult):
            if movie_details.provider_name:
                provider_name = movie_details.provider_name
                logger.debug(
                    "Extracted provider_name '%s' from movie_details for movie ID: %s",
                    provider_name,
                    movie_id
                )
        
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
    # Try to get provider_name from multiple sources
    provider_name = callback_data.get("provider_name")
    
    if movie_details_data := callback_data.get("movie_details"):
        try:
            result = MovieSearchResult.model_validate(movie_details_data)
            # Prioritize provider_name from cached data (most reliable)
            if result.provider_name:
                provider_name = result.provider_name
                logger.debug(
                    "Using provider_name '%s' from cached movie_details for movie ID: %s",
                    provider_name,
                    movie_id
                )
            elif provider_name:
                logger.debug(
                    "Using provider_name '%s' from callback_data for movie ID: %s",
                    provider_name,
                    movie_id
                )
            else:
                logger.warning(
                    "No provider_name found in callback_data or cached movie_details for movie ID: %s",
                    movie_id
                )
            
            # Only use cached data if it has full details
            # Otherwise, fetch full details from provider
            if result.has_full_details:
                logger.info(
                    "Using cached full movie details for movie ID: %s (provider: %s)",
                    movie_id,
                    provider_name or "unknown"
                )
                return result
            else:
                logger.info(
                    "Cached movie details for ID %s are incomplete (has_full_details=False), fetching full details from provider: %s",
                    movie_id,
                    provider_name or "default"
                )
        except ValidationError as exc:
            logger.warning(
                "Failed to use cached movie details for ID %s: %s. Refetching.",
                movie_id,
                exc,
            )
    
    # Get provider by name if specified, otherwise use default
    if provider_name:
        try:
            provider = get_torrent_provider(provider_name)
            logger.info(
                "Using provider '%s' for movie ID: %s",
                provider_name,
                movie_id
            )
        except KeyError:
            logger.warning(
                "Provider '%s' not found, falling back to default provider for movie ID: %s",
                provider_name,
                movie_id
            )
            provider = torrent_provider
    else:
        logger.warning(
            "No provider_name specified, using default provider for movie ID: %s",
            movie_id
        )
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
    
    # Log message length for debugging
    message_length = len(message_caption)
    if message_length > TELEGRAM_MESSAGE_SAFE_LENGTH:
        logger.warning(
            "Movie details message is long (%d chars), may be truncated",
            message_length
        )
    logger.debug(f"Sending movie details ({message_length} chars): {message_caption[:200]}...")

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
    
    try:
        await callback_query.message.edit_text(
            message_caption, parse_mode=SULGUK_PARSE_MODE, reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        # Handle message too long error
        if "MESSAGE_TOO_LONG" in str(e) or "message is too long" in str(e).lower():
            logger.error(
                "Message too long (%d chars) for movie ID %s, sending truncated version",
                len(message_caption),
                movie_id,
                exc_info=True
            )
            # Try sending a minimal version
            minimal_message = (
                f"<b>{movie_details.name}</b> ({movie_details.year})<br/>"
                f"<b>Качество</b>: {movie_details.video_quality or 'N/A'}<br/>"
                f"<i>Детальная информация слишком длинная для отображения.</i><br/>"
                f"<i>Используйте кнопку ниже для просмотра на трекере.</i>"
            )
            try:
                await callback_query.message.edit_text(
                    minimal_message, parse_mode=SULGUK_PARSE_MODE, reply_markup=reply_markup
                )
            except Exception as e2:
                logger.error("Failed to send minimal message: %s", e2, exc_info=True)
                await callback_query.message.answer(
                    "Информация о торренте слишком длинная для отображения. "
                    "Используйте кнопку для просмотра на трекере."
                )
        else:
            # Re-raise other TelegramBadRequest errors
            raise


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
    # If provider_name is not specified, we can't determine the correct provider
    # In this case, we should log a warning and try to use a fallback
    if provider_name:
        try:
            provider = get_torrent_provider(provider_name)
        except KeyError:
            logger.warning(
                "Provider '%s' not found for movie ID %s, using default provider for tracker URL",
                provider_name,
                movie_id
            )
            provider = get_torrent_provider()  # Use default
    else:
        logger.warning(
            "No provider_name specified for movie ID %s, using default provider for tracker URL",
            movie_id
        )
        provider = get_torrent_provider()  # Use default
    
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


# Telegram message length limit (4096 characters)
TELEGRAM_MESSAGE_MAX_LENGTH = 4096
# Reserve some space for safety margin and potential HTML tag closing
TELEGRAM_MESSAGE_SAFE_LENGTH = 4000


def _truncate_html_message(message: str, max_length: int = TELEGRAM_MESSAGE_SAFE_LENGTH) -> str:
    """Truncate HTML message to fit Telegram's message length limit.
    
    Tries to truncate at word boundaries and close HTML tags properly.
    """
    if len(message) <= max_length:
        return message
    
    # Try to find a good truncation point (at word boundary, before <br/>)
    truncated = message[:max_length]
    
    # Find last <br/> tag before truncation point
    last_br = truncated.rfind("<br/>")
    if last_br > max_length - 100:  # If <br/> is close to the end, use it
        truncated = message[:last_br + 5]  # Include <br/>
    
    # Add truncation indicator
    truncated += "<br/><i>...(сообщение обрезано)</i>"
    
    # Ensure we don't exceed limit even with truncation indicator
    if len(truncated) > TELEGRAM_MESSAGE_MAX_LENGTH:
        # More aggressive truncation
        available = TELEGRAM_MESSAGE_MAX_LENGTH - len("<br/><i>...(сообщение обрезано)</i>")
        truncated = message[:available] + "<br/><i>...(сообщение обрезано)</i>"
    
    return truncated


def format_movie_details_message(movie_details: MovieDetails) -> str:
    """Format movie details into HTML message.
    
    Automatically truncates if message exceeds Telegram's 4096 character limit.
    """
    bold = html_decoration.bold
    code = html_decoration.code
    
    # Build basic info (always include)
    basic_info = (
        f"{bold('Название')}: {movie_details.name}<br/>"
        f"{bold('Год')}: {movie_details.year}<br/>"
        f"{bold('Жанр')}: {', '.join(movie_details.genres)}<br/>"
        f"{bold('Режисер')}: {movie_details.director}<br/>"
        f"{bold('Актеры')}: {', '.join(movie_details.actors[:5])}<br/><br/>"
        f"{bold('Рейтинги')}:<br/>"
        f"- IMDB: {code(movie_details.ratings.imdb)}<br/>"
        f"- Kinopoisk: {code(movie_details.ratings.kinopoisk)}<br/><br/>"
    )
    
    # Build torrent details section
    torrent_section = ""
    if movie_details.torrent_html_content:
        # If HTML content is available, use it but limit its length
        html_content = movie_details.torrent_html_content
        # Reserve space for basic info and section header
        available_for_html = TELEGRAM_MESSAGE_SAFE_LENGTH - len(basic_info) - len("<b>Torrent Details</b>:<br/>")
        if len(html_content) > available_for_html:
            # Truncate HTML content
            html_content = html_content[:available_for_html - 50] + "<br/><i>...(детали обрезаны)</i>"
        torrent_section = f"<b>Torrent Details</b>:<br/>{html_content}"
    else:
        # Fallback to parsed torrent_details
        torrent_section = f"<b>Torrent Details</b>:<br/>"
        max_details = 50  # Limit number of details to prevent overflow
        for detail in movie_details.torrent_details[:max_details]:
            value = detail.value or "-"
            # Truncate long values
            if len(value) > 200:
                value = value[:197] + "..."
            torrent_section += f"- {bold(detail.key)} {code(value)}<br/>"
        
        if len(movie_details.torrent_details) > max_details:
            torrent_section += f"<i>...(еще {len(movie_details.torrent_details) - max_details} деталей)</i><br/>"
    
    message = basic_info + torrent_section
    
    # Final truncation check
    return _truncate_html_message(message)


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
