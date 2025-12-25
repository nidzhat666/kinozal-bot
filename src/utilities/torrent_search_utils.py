from __future__ import annotations

import asyncio
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
from models.search_provider_types import MediaDetails
from torrents import get_torrent_provider
from utilities.media_utils import (
    calculate_similarity,
    clean_title_for_query,
    is_season_match,
    parse_video_quality,
)
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
    media_details: MediaDetails | None = None,
    season_number: int | None = None,
) -> None:
    queries = {query}

    if media_details:
        suffix = ""
        season_variants_str = ""
        
        if season_number is not None and media_details.is_series:
            s_num = str(season_number)
            season_variants = [
                f"сезон {s_num}",
                f"season {s_num}",
                f"S{season_number:02d}",
            ]
            season_variants_str = f" ({'|'.join(season_variants)})"
        elif media_details.year and not media_details.is_series:
            suffix = f" ({media_details.year})"

        titles_to_check = [
            t for t in [media_details.title, media_details.original_title] if t
        ]
        
        for title in titles_to_check:
            clean_title = clean_title_for_query(title)
            if season_variants_str:
                queries.add(f"{clean_title}{season_variants_str}")
            else:
                queries.add(f"{clean_title}{suffix}")

    queries = {q for q in queries if q.strip()}
    logger.info("Performing parallel search for queries: %s", queries)

    provider = get_torrent_provider()
    target_message = callback_query.message if callback_query else message

    tasks = [
        provider.search(
            q,
            requested_item=requested_item,
            requested_type=requested_type,
        )
        for q in queries
    ]

    try:
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        raw_results = []
        for res in results_list:
            if isinstance(res, Exception):
                logger.warning(f"Search failed for one of the queries: {res}")
            elif isinstance(res, list):
                raw_results.extend(res)

    except Exception as exc:
        logger.error(
            "Torrent search critical failure: %s", exc, exc_info=True
        )
        await target_message.edit_text("Не удалось выполнить поиск по торрентам.")
        return

    results = _filter_and_process_results(raw_results, media_details, season_number)

    if not results:
        logger.info("No torrent results found after filtering")
        await target_message.edit_text("По запросу ничего не найдено.")
        return

    results = _sort_and_group_results(results)

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

        message_text = f"Выберите результат{' для «' + requested_item + '»' if requested_item else ''}:"
        await target_message.edit_text(message_text, reply_markup=keyboard)
        logger.info(
            "Sent %d torrent search results (merged from %d queries)", len(results), len(queries)
        )

    except Exception as exc:
        logger.error(
            "Failed to send torrent search results: %s",
            exc,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось отобразить результаты поиска.")


def _filter_and_process_results(
    raw_results: list[MovieSearchResult],
    media_details: MediaDetails | None,
    season_number: int | None,
) -> list[MovieSearchResult]:
    seen_movie_ids = set()
    results = []

    expected_titles = []
    if media_details:
        expected_titles = [
            t for t in [media_details.title, media_details.original_title] if t
        ]

    for result in raw_results:
        if result.id in seen_movie_ids or not result.seeds:
            continue

        if not result.video_quality:
            result.video_quality = parse_video_quality(
                result.search_name or result.name
            )

        result_name = result.search_name or result.name

        if season_number is not None and not is_season_match(
            result_name, season_number
        ):
            continue

        if expected_titles and not _is_fuzzy_match(result_name, expected_titles):
            continue

        seen_movie_ids.add(result.id)
        results.append(result)

    return results


def _is_fuzzy_match(result_name: str, expected_titles: list[str]) -> bool:
    result_clean = clean_title_for_query(result_name).lower()

    for expected in expected_titles:
        expected_clean = clean_title_for_query(expected).lower()
        if expected_clean in result_clean:
            return True
        if calculate_similarity(expected, result_name) > 0.4:
            return True

    return False


def _sort_and_group_results(
    results: list[MovieSearchResult],
) -> list[MovieSearchResult]:
    def get_quality(r: MovieSearchResult) -> str:
        return r.video_quality or "N/A"

    results.sort(key=get_quality)
    best_results = []

    for _, group in groupby(results, key=get_quality):
        best_in_group = max(group, key=lambda r: r.seeds if r.seeds is not None else -1)
        best_results.append(best_in_group)

    best_results.sort(
        key=lambda r: r.seeds if r.seeds is not None else -1, reverse=True
    )
    return best_results


def format_torrent_search_results(
    results: list[MovieSearchResult],
    results_cache_key: str,
    *,
    back_callback_key: str | None = None,
    back_button_text: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = []

    for result in results:
        quality = result.video_quality or "N/A"
        size = result.size or "N/A"
        seeds = result.seeds if result.seeds is not None else "?"
        peers = result.peers if result.peers is not None else "?"

        button_label = f"{quality} | {size} | ⬆️{seeds} ⬇️{peers}"

        callback_payload = {
            "action": MOVIE_DETAILED_CALLBACK,
            "movie_id": result.id,
            "results_cache_key": results_cache_key,
        }

        if result.has_full_details:
            callback_payload["movie_details"] = result.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )

        movie_details_uuid = redis_callback_save(callback_payload)
        buttons.append(
            [InlineKeyboardButton(text=button_label, callback_data=movie_details_uuid)]
        )

    if back_callback_key:
        back_text = back_button_text or "Назад"
        buttons.append(
            [InlineKeyboardButton(text=back_text, callback_data=back_callback_key)]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
