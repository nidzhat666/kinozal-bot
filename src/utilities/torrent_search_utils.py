from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from itertools import groupby

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import MOVIE_DETAILED_CALLBACK
from models.movie_detail_service_types import MovieSearchResult, VideoQuality
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
            media_details=media_details,
            season_number=season_number,
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
    quality_counter: Counter[str] = Counter()
    
    # Stats for debugging
    skip_reasons: Counter[str] = Counter()

    expected_titles = []
    if media_details:
        expected_titles = [
            t for t in [media_details.title, media_details.original_title] if t
        ]

    for result in raw_results:
        result_name = result.search_name or result.name
        
        if result.id in seen_movie_ids:
            skip_reasons["duplicate"] += 1
            continue
            
        if not result.seeds:
            skip_reasons["no_seeds"] += 1
            continue

        if not result.video_quality:
            result.video_quality = parse_video_quality(result_name)

        if season_number is not None and not is_season_match(
            result_name, season_number
        ):
            skip_reasons["season_mismatch"] += 1
            logger.info(
                "SKIP season_mismatch (S%02d): [%s] %s",
                season_number,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue

        if expected_titles and not _is_fuzzy_match(result_name, expected_titles):
            skip_reasons["title_mismatch"] += 1
            logger.info(
                "SKIP title_mismatch: [%s] %s",
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue

        seen_movie_ids.add(result.id)
        results.append(result)
        quality_counter[result.video_quality or "Unknown"] += 1
        logger.info(
            "ACCEPTED: [%s] seeds=%s %s",
            result.video_quality or "N/A",
            result.seeds,
            result_name[:80],
        )

    _log_quality_stats(quality_counter, len(raw_results), len(results))
    
    if skip_reasons:
        logger.info(
            "Skip reasons: %s",
            ", ".join(f"{reason}: {count}" for reason, count in skip_reasons.most_common()),
        )
    
    return results


def _log_quality_stats(
    quality_counter: Counter[str],
    total_raw: int,
    total_filtered: int,
) -> None:
    """Log statistics about found video qualities."""
    if not quality_counter:
        logger.info("No torrents found after filtering (raw: %d)", total_raw)
        return

    # Sort by count descending
    sorted_stats = quality_counter.most_common()
    stats_str = ", ".join(f"{quality}: {count}" for quality, count in sorted_stats)
    
    logger.info(
        "Quality stats (filtered %d/%d): %s",
        total_filtered,
        total_raw,
        stats_str,
    )


def _is_fuzzy_match(result_name: str, expected_titles: list[str]) -> bool:
    """Check if result name matches expected titles with stricter matching.
    
    Matches if:
    1. Expected title is at the start of result name (with optional prefix like "сезон")
    2. Expected title is the main title (before separators like ":", "/", "-")
    3. High similarity (>0.7) for fuzzy matching
    """
    result_clean = clean_title_for_query(result_name).lower()

    for expected in expected_titles:
        expected_clean = clean_title_for_query(expected).lower()
        
        # Remove common prefixes first
        prefixes = ["сезон", "season", "s"]
        result_without_prefix = result_clean
        for prefix in prefixes:
            # Match "сезон 1", "season 1", "s01", etc.
            prefix_pattern = rf'^{re.escape(prefix)}\s*\d+'
            if re.match(prefix_pattern, result_clean):
                result_without_prefix = re.sub(prefix_pattern, '', result_clean).strip()
                break
        
        # Extract main title (before separators like ":", "/", "-")
        # This handles cases like "Wise Guy: David Chase and the Sopranos"
        main_title_match = re.match(r'^([^:\-/\|]+)', result_without_prefix)
        if main_title_match:
            main_title = main_title_match.group(1).strip()
            
            if main_title.startswith(expected_clean):
                return True
            
            # Check if expected title words appear at the start of main title
            expected_words = expected_clean.split()
            main_title_words = main_title.split()
            if len(main_title_words) >= len(expected_words):
                if main_title_words[:len(expected_words)] == expected_words:
                    return True
        
        # Also check if expected title is at the very start (after prefixes)
        if result_without_prefix.startswith(expected_clean):
            return True
        
        # Stricter similarity threshold for fuzzy matching
        if calculate_similarity(expected, result_name) > 0.7:
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
    media_details: MediaDetails | None = None,
    season_number: int | None = None,
) -> InlineKeyboardMarkup:
    """Format torrent search results into Telegram inline keyboard."""
    buttons = [
        _create_result_button(result, results_cache_key, media_details, season_number)
        for result in results
    ]

    if back_callback_key:
        buttons.append([
            InlineKeyboardButton(
                text=back_button_text or "Назад",
                callback_data=back_callback_key
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _create_result_button(
    result: MovieSearchResult,
    results_cache_key: str,
    media_details: MediaDetails | None,
    season_number: int | None = None,
) -> list[InlineKeyboardButton]:
    """Create a single result button with metadata."""
    quality = result.video_quality or "N/A"
    size = result.size or "N/A"
    seeds = result.seeds if result.seeds is not None else "?"
    peers = result.peers if result.peers is not None else "?"
    
    # Get rating emoji for quality
    rating_emoji = _get_quality_rating_emoji(result.video_quality)
    
    label = f"{rating_emoji}{quality} | {size} | ⬆️{seeds} ⬇️{peers}"
    
    payload = {
        "action": MOVIE_DETAILED_CALLBACK,
        "movie_id": result.id,
        "results_cache_key": results_cache_key,
    }
    
    if media_details:
        payload["tmdb_info"] = {
            "original_title": media_details.original_title,
            "year": media_details.year,
            "quality": result.video_quality,
        }
        if season_number is not None and media_details.is_series:
            payload["tmdb_info"]["season"] = season_number
    
    if result.has_full_details:
        payload["movie_details"] = result.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    
    callback_data = redis_callback_save(payload)
    return [InlineKeyboardButton(text=label, callback_data=callback_data)]


def _get_quality_rating_emoji(quality: VideoQuality | str | None) -> str:
    """Get rating emoji for quality, handling both VideoQuality enum and string."""
    if quality is None:
        return ""
    
    # If already VideoQuality enum, use rating_emoji directly
    if isinstance(quality, VideoQuality):
        return quality.rating_emoji + " "
    
    # If string, try to convert to VideoQuality
    if isinstance(quality, str):
        try:
            video_quality = VideoQuality(quality)
            return video_quality.rating_emoji + " "
        except ValueError:
            pass
    
    return ""
