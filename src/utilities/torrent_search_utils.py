from __future__ import annotations

import logging
from itertools import groupby

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import MOVIE_DETAILED_CALLBACK
from models.movie_detail_service_types import MovieSearchResult
from torrents import get_torrent_provider
from utilities.groq_utils import filter_movies_with_groq
from utilities.handlers_utils import redis_callback_save

logger = logging.getLogger(__name__)


async def perform_torrent_search(
    query: str,
    message: Message,
    callback_query: CallbackQuery | None = None,
    *,
    requested_item: str | None = None,
    requested_type: str | None = None,
    back_callback_key: str | None = None,
    back_button_text: str | None = None,
) -> None:
    logger.info("Searching torrents for query '%s'", query)

    provider = get_torrent_provider()
    target_message = callback_query.message if callback_query else message

    try:
        raw_results = await provider.search(
            query,
            requested_item=requested_item,
            requested_type=requested_type,
        )
    except Exception as exc:
        logger.error(
            "Torrent search failed for query '%s': %s",
            query,
            exc,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось выполнить поиск по торрентам.")
        return

    seen_movie_ids: set[str] = set()
    results: list[MovieSearchResult] = []
    for result in raw_results:
        if result.id in seen_movie_ids:
            continue
        if result.seeds:
            seen_movie_ids.add(result.id)
            results.append(result)

    if requested_item and requested_type:
        results = await filter_movies_with_groq(
            results,
            requested_item=requested_item,
            requested_type=requested_type,
        )

    if not results:
        logger.info("No torrent results found for query '%s'", query)
        await target_message.edit_text("По запросу ничего не найдено.")
        return

    # Group by quality and pick the one with the most seeds
    def get_quality(result: MovieSearchResult) -> str:
        return result.video_quality or "N/A"

    results.sort(key=get_quality)
    best_results: list[MovieSearchResult] = []
    for _, group in groupby(results, key=get_quality):
        best_in_group = max(list(group), key=lambda r: r.seeds if r.seeds is not None else -1)
        best_results.append(best_in_group)

    # Sort by seeds descending for better presentation
    best_results.sort(key=lambda r: r.seeds if r.seeds is not None else -1, reverse=True)
    results = best_results

    if not results:
        logger.info("No torrent results left after filtering for query '%s'", query)
        await target_message.edit_text("По запросу ничего не найдено.")
        return

    results_json = [r.model_dump(mode="json") for r in results]
    results_cache_data = {
        "results": results_json,
        "requested_item": requested_item,
        "back_callback_key": back_callback_key,
        "back_button_text": back_button_text,
    }
    results_cache_key = redis_callback_save(results_cache_data)

    try:
        keyboard = format_torrent_search_results(
            results,
            results_cache_key,
            back_callback_key=back_callback_key,
            back_button_text=back_button_text,
        )
        if not keyboard.inline_keyboard:
            await target_message.edit_text("По запросу ничего не найдено.")
            return

        message_text = "Выберите результат"
        if requested_item:
            message_text += f" для «{requested_item}»:"
        else:
            message_text += ":"

        await target_message.edit_text(message_text, reply_markup=keyboard)
        logger.info("Sent %d torrent search results for query '%s'", len(results), query)
    except Exception as exc:
        logger.error(
            "Failed to send torrent search results for query '%s': %s",
            query,
            exc,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось отобразить результаты поиска.")


def format_torrent_search_results(
    results: list[MovieSearchResult],
    results_cache_key: str,
    *,
    back_callback_key: str | None = None,
    back_button_text: str | None = None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for result in results:
        quality = result.video_quality or "N/A"
        size = result.size or "N/A"
        seeds = result.seeds if result.seeds is not None else "?"
        peers = result.peers if result.peers is not None else "?"
        button_label = f"{quality} | {size} | ⬆️{seeds} ⬇️{peers}"
        movie_details_payload = None
        if result.has_full_details:
            movie_details_payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        callback_payload = {
            "action": MOVIE_DETAILED_CALLBACK,
            "movie_id": result.id,
            "results_cache_key": results_cache_key,
        }
        if movie_details_payload is not None:
            callback_payload["movie_details"] = movie_details_payload
        movie_details_uuid = redis_callback_save(callback_payload)
        buttons.append([InlineKeyboardButton(text=button_label, callback_data=movie_details_uuid)])

    if back_callback_key:
        back_text = back_button_text or "Назад"
        buttons.append([InlineKeyboardButton(text=back_text, callback_data=back_callback_key)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard
