from __future__ import annotations

import logging

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pydantic import ValidationError

from bot.constants import (
    MEDIA_LIST_CALLBACK,
    MEDIA_SELECT_CALLBACK,
    SEASON_SELECT_CALLBACK,
)
from models.movie_detail_service_types import MovieSearchResult
from models.search_provider_types import MediaDetails, MediaItem
from services.exceptions import KinopoiskApiError, NoResultsFoundError, TmdbApiError
from services.search_integrations.registry import get_search_provider
from utilities.handlers_utils import redis_callback_get, redis_callback_save
from utilities.torrent_search_utils import format_torrent_search_results

logger = logging.getLogger(__name__)


async def show_media_results(
    query: str,
    message: Message,
) -> None:
    logger.info("Searching for query '%s'", query)
    search_provider = get_search_provider()
    search_response = await search_provider.search(query)
    movies = search_response.results
    if not movies:
        raise NoResultsFoundError(f"Search returned no results for '{query}'.")

    buttons: list[list[InlineKeyboardButton]] = []
    for movie in movies[:10]:
        if not movie.title:
            continue
        requested_item = movie.title or movie.original_title
        requested_type = "series" if movie.is_series else "movie"
        callback_key = redis_callback_save(
            {
                "action": MEDIA_SELECT_CALLBACK,
                "query": query,
                "movie_id": movie.provider_id,
                "movie": movie.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                "requested_item": requested_item,
                "requested_type": requested_type,
            }
        )
        media_type_label = "Сериал" if movie.is_series else "Фильм"
        caption = (
            f"{media_type_label}: {movie.title} ({movie.year})"
            if movie.year
            else movie.title
        )
        buttons.append([InlineKeyboardButton(text=caption, callback_data=callback_key)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.edit_text(
        f"Результаты поиска для «{query}». Выберите подходящий вариант:",
        reply_markup=keyboard,
    )


async def show_season_choices(
    callback_query: CallbackQuery,
    movie_details: MediaDetails,
    seasons: list[int],
    original_query: str,
    requested_item: str | None,
    requested_type: str,
) -> None:
    buttons: list[list[InlineKeyboardButton]] = []
    movie_dump = movie_details.model_dump(mode="json", by_alias=True, exclude_none=True)
    search_context = original_query or requested_item or movie_details.title

    season_year_map = {s.season_number: s.year for s in movie_details.seasons}

    for season in seasons:
        season_year = season_year_map.get(season)
        button_label = f"Сезон {season}"
        if season_year:
            button_label += f" ({season_year})"

        callback_key = redis_callback_save(
            {
                "action": SEASON_SELECT_CALLBACK,
                "season": season,
                "movie_id": movie_details.provider_id,
                "movie": movie_dump,
                "movie_details": movie_dump,
                "season_year": season_year,
                "original_query": original_query,
                "requested_item": requested_item,
                "requested_type": requested_type,
            }
        )
        buttons.append(
            [InlineKeyboardButton(text=button_label, callback_data=callback_key)]
        )

    back_callback = redis_callback_save(
        {
            "action": MEDIA_LIST_CALLBACK,
            "query": search_context,
        }
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="Назад к результатам поиска", callback_data=back_callback
            )
        ]
    )

    title = movie_details.title
    header = f"{title}"
    if movie_details.year:
        header += f" ({movie_details.year})"

    description = movie_details.description or ""
    text_parts = [header]
    if description:
        text_parts.extend(["", description])
    text_parts.extend(["", "Выберите сезон:"])

    await callback_query.message.edit_text(
        "\n".join(filter(None, text_parts)),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def get_details_from_callback(
    callback_data: dict,
) -> MediaDetails | None:
    movie_id = callback_data.get("movie_id")
    movie_details_payload = callback_data.get("movie_details")
    if movie_details_payload:
        try:
            return MediaDetails.model_validate(movie_details_payload)
        except ValidationError:
            logger.debug("Failed to validate cached MediaDetails payload.")

    movie_payload = callback_data.get("movie")

    if not movie_id:
        movie_payload = movie_payload or movie_details_payload
        if movie_payload:
            try:
                return MediaDetails.model_validate(movie_payload)
            except ValidationError:
                try:
                    base_info = MediaItem.model_validate(movie_payload)
                    return MediaDetails(**base_info.model_dump())
                except ValidationError:
                    logger.debug(
                        "Failed to build MediaDetails from cached data without movie_id."
                    )
        return None

    # Always try to fetch fresh details first to get season info.
    try:
        search_provider = get_search_provider()
        return await search_provider.get_details(movie_id)
    except (KinopoiskApiError, TmdbApiError) as exc:
        logger.warning(
            "Failed to fetch details for id %s: %s. Falling back to cached data.",
            movie_id,
            exc,
        )
        payload = movie_payload or movie_details_payload
        if payload:
            try:
                return MediaDetails.model_validate(payload)
            except ValidationError:
                try:
                    base_info = MediaItem.model_validate(payload)
                    return MediaDetails(**base_info.model_dump())
                except ValidationError:
                    logger.debug("Failed to create MediaDetails from cached payload.")
    return None


async def show_cached_torrent_results(
    message: Message,
    cache_key: str,
) -> bool:
    cached_data = redis_callback_get(cache_key)
    if not cached_data:
        return False

    results_json = cached_data.get("results", [])
    requested_item = cached_data.get("requested_item")
    back_callback_key = cached_data.get("back_callback_key")
    back_button_text = cached_data.get("back_button_text")

    try:
        results = [MovieSearchResult.model_validate(r) for r in results_json]
        keyboard = format_torrent_search_results(
            results,
            cache_key,
            back_callback_key=back_callback_key,
            back_button_text=back_button_text,
        )

        message_text = "Выберите результат"
        if requested_item:
            message_text += f" для «{requested_item}»:"
        else:
            message_text += ":"

        await message.edit_text(message_text, reply_markup=keyboard)
        return True
    except Exception as e:
        logger.error(f"Failed to show cached results: {e}", exc_info=True)
        return False
