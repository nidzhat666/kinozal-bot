from __future__ import annotations

import asyncio
import re
from collections import Counter
from itertools import groupby
from time import perf_counter
from typing import TYPE_CHECKING

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import MOVIE_DETAILED_CALLBACK
from models.movie_detail_service_types import MovieSearchResult, VideoQuality
from torrents import get_active_providers

if TYPE_CHECKING:
    from models.search_provider_types import MediaDetails
from utilities.handlers_utils import redis_callback_save
from utilities.logger_utils import get_logger
from utilities.media_utils import (
    calculate_similarity,
    clean_title_for_query,
    is_season_match,
    parse_video_quality,
    parse_year,
)

logger = get_logger(__name__)


def _build_year_range_queries(clean_titles: list[str], year: int | str | None) -> set[str]:
    """Build search queries with year range (year-1, year, year+1)."""
    queries = set()
    parsed_year = parse_year(year)
    if not parsed_year:
        return queries

    year_range = [y for y in [parsed_year - 1, parsed_year, parsed_year + 1] if 1900 <= y <= 2100]
    if not year_range:
        return queries

    year_range_str = " | ".join(str(y) for y in year_range)
    for clean_title in clean_titles:
        queries.add(f"{clean_title} {year_range_str}")
    if len(clean_titles) > 1:
        combined_titles = "|".join(sorted(clean_titles))
        queries.add(f"({combined_titles}) + ({year_range_str})")
    return queries


def _build_season_queries(
    clean_titles: list[str], season_number: int, year: int | str | None
) -> set[str]:
    """Build search queries for series season with optional year."""
    queries = set()
    season_variants = f"сезон {season_number}|season {season_number}|S{season_number:02d}"
    parsed_year = parse_year(year)

    for clean_title in clean_titles:
        queries.add(f"{clean_title} ({season_variants})")
        if parsed_year:
            year_range = [
                y for y in [parsed_year - 1, parsed_year, parsed_year + 1] if 1900 <= y <= 2100
            ]
            if year_range:
                year_range_str = " | ".join(str(y) for y in year_range)
                queries.add(f"{clean_title} ({season_variants}) ({year_range_str})")

    return queries


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
    season_year: int | None = None,
) -> None:
    """Perform torrent search across active providers and display results."""
    queries = {query}

    if media_details:
        titles = [t for t in [media_details.title, media_details.original_title] if t]
        clean_titles = [clean_title_for_query(t) for t in titles]

        if season_number is not None and media_details.is_series:
            year_to_use = season_year if season_year else media_details.year
            queries.update(_build_season_queries(clean_titles, season_number, year_to_use))
        elif not media_details.is_series:
            year_queries = _build_year_range_queries(clean_titles, media_details.year)
            queries.update(year_queries if year_queries else clean_titles)
        else:
            if media_details.year:
                year_queries = _build_year_range_queries(clean_titles, media_details.year)
                queries.update(year_queries if year_queries else clean_titles)
            else:
                queries.update(clean_titles)

    queries = {q for q in queries if q.strip()}
    started_at = perf_counter()
    search_logger = logger.bind(component="utility", operation="torrent_search")
    search_logger.info(
        "Performing parallel search",
        query_count=len(queries),
        queries=list(queries),
        requested_item=requested_item,
        requested_type=requested_type,
    )

    active_providers = get_active_providers()
    if not active_providers:
        target_message = callback_query.message if callback_query else message
        await target_message.edit_text("Нет активных торрент-провайдеров. Проверьте настройки.")
        return

    search_logger.info(
        "Searching in active providers",
        provider_count=len(active_providers),
        providers=[p.name for p in active_providers],
    )
    target_message = callback_query.message if callback_query else message

    tasks_with_info = [
        (
            provider,
            q,
            provider.search(q, requested_item=requested_item, requested_type=requested_type),
        )
        for q in queries
        for provider in active_providers
    ]

    tasks = [task for _, _, task in tasks_with_info]

    try:
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        raw_results = []
        provider_stats: dict[str, int] = {}

        for (provider, query, _), res in zip(tasks_with_info, results_list, strict=True):
            provider_name = provider.name
            if isinstance(res, Exception):
                search_logger.warning(
                    "Search failed",
                    provider=provider_name,
                    query=query,
                    error_type=type(res).__name__,
                    error_message=str(res),
                )
                provider_stats[provider_name] = provider_stats.get(provider_name, 0)
            elif isinstance(res, list):
                count = len(res)
                provider_stats[provider_name] = provider_stats.get(provider_name, 0) + count
                raw_results.extend(res)
                search_logger.info(
                    "Found torrents", provider=provider_name, query=query, count=count
                )

        for provider_name, total_count in provider_stats.items():
            search_logger.info(
                "Total results across all queries",
                provider=provider_name,
                total_count=total_count,
            )

    except Exception as exc:
        search_logger.error(
            "Torrent search critical failure",
            error_type=type(exc).__name__,
            error_message=str(exc),
            exc_info=True,
        )
        await target_message.edit_text("Не удалось выполнить поиск по торрентам.")
        return

    results = _filter_and_process_results(raw_results, media_details, season_number, season_year)

    filter_logger = logger.bind(component="utility", operation="filter_results")
    filter_logger.info(
        "Filter results completed",
        count_before=len(raw_results),
        count_after=len(results),
        filtered_count=len(raw_results) - len(results),
    )

    if not results:
        duration_ms = int((perf_counter() - started_at) * 1000)
        search_logger.info("No torrent results found after filtering", duration_ms=duration_ms)
        await target_message.edit_text("По запросу ничего не найдено.")
        return

    results = _sort_and_group_results(results)
    _log_final_results_stats(results)

    results_cache_key = redis_callback_save(
        {
            "results": [r.model_dump(mode="json") for r in results],
            "requested_item": requested_item,
            "back_callback_key": back_callback_key,
            "back_button_text": back_button_text,
        }
    )

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

        message_text = (
            f"Выберите результат{' для «' + requested_item + '»' if requested_item else ''}:"
        )
        await target_message.edit_text(message_text, reply_markup=keyboard)
        duration_ms = int((perf_counter() - started_at) * 1000)
        search_logger.info(
            "Sent torrent search results",
            result_count=len(results),
            query_count=len(queries),
            duration_ms=duration_ms,
        )

    except Exception as exc:
        duration_ms = int((perf_counter() - started_at) * 1000)
        search_logger.error(
            "Failed to send torrent search results",
            error_type=type(exc).__name__,
            error_message=str(exc),
            duration_ms=duration_ms,
            exc_info=True,
        )
        await target_message.edit_text("Не удалось отобразить результаты поиска.")


def _is_audio_release(result_name: str) -> bool:
    """Check if result is an audio-only release."""
    result_lower = result_name.lower()

    strict_audio_keywords_word_boundary = [r"\bost\b", r"\bscore\b"]
    strict_audio_keywords_substring = [
        "audio pack",
        "[audio pack]",
        "soundtrack",
        "саундтрек",
    ]
    conditional_audio_keywords = [
        "аудиодорож",
        "озвучк",
        "mp3",
        "flac",
        "albums",
        "album",
        "tracks",
        "track",
        "lossless",
        "аудио",
        "музыка",
    ]
    audio_codecs = ["ac3", "dts"]

    for pattern in strict_audio_keywords_word_boundary:
        if re.search(pattern, result_lower):
            return True

    for keyword in strict_audio_keywords_substring:
        if keyword in result_lower:
            return True

    if not _has_video_markers(result_name):
        for keyword in conditional_audio_keywords:
            if keyword in result_lower:
                return True
        if any(codec in result_lower for codec in audio_codecs):
            return True

    return False


def _is_disc_image(result_name: str) -> bool:
    """Check if result is a disc image format."""
    result_lower = result_name.lower()
    disc_keywords = [
        "dvd9",
        "dvd-9",
        "dvd5",
        "dvd-5",
        "ntsc",
        "pal",
        "2 x dvd-9",
        "2 x dvd9",
    ]
    return any(keyword in result_lower for keyword in disc_keywords)


def _has_video_markers(result_name: str) -> bool:
    """Check if result name contains video quality markers."""
    result_lower = result_name.lower()
    video_markers = [
        "1080p",
        "2160p",
        "720p",
        "480p",
        "576p",
        "1080i",
        "bdrip",
        "bd-rip",
        "bluray",
        "blu-ray",
        "blu ray",
        "web-dl",
        "webdl",
        "webrip",
        "web-rip",
        "web dl",
        "hdrip",
        "hd-rip",
        "hd rip",
        "dvdrip",
        "dvd-rip",
        "dvd rip",
        "remux",
        "bdremux",
        "bd-remux",
        "uhd",
        "4k",
        "hdr",
        "hdr10",
        "hdr10+",
        "dolby vision",
        "dovi",
        "dv",
        "hevc",
        "x265",
        "h265",
        "x264",
        "h264",
        "avc",
    ]
    return any(marker in result_lower for marker in video_markers)


def _has_multiple_resolutions(result_name: str) -> bool:
    """Check if result contains multiple video resolutions."""
    result_lower = result_name.lower()
    resolutions = {
        "1080p": r"\b1080p\b",
        "720p": r"\b720p\b",
        "2160p": r"\b2160p\b",
        "4k": r"\b4k\b",
        "480p": r"\b480p\b",
        "576p": r"\b576p\b",
    }

    found_resolutions = [
        name for name, pattern in resolutions.items() if re.search(pattern, result_lower)
    ]
    return (
        len(found_resolutions) > 1 and "1080p" in found_resolutions and "720p" in found_resolutions
    )


def _has_multiple_video_tracks(result_name: str) -> bool:
    """Check if result indicates multiple video tracks."""
    result_lower = result_name.lower()
    patterns = [
        r"\d+\s+видео",
        r"\d+\s+video",
        r"dual\s+video",
        r"multiple\s+video",
        r"двойное\s+видео",
        r"две\s+видеодорожки",
        r"2\s+видеодорожки",
        r"видеодорожки\s*\d+",
        r"video\s+tracks?\s*\d+",
        r"\d+\s+video\s+tracks?",
    ]
    return any(re.search(pattern, result_lower) for pattern in patterns)


def _is_season_pack(result_name: str, target_season: int | None) -> bool:
    """Check if result is a multi-season pack."""
    if target_season is None:
        return False

    result_lower = result_name.lower()
    pack_patterns = [
        r"\d+\s*-\s*\d+\s*сезон",
        r"\d+\s*-\s*\d+\s*сезоны",
        r"s\d+\s*-\s*s\d+",
        r"s\d+\s*-\s*\d+",
        r"\d+\s*-\s*s\d+",
        r"сезоны?\s*\d+\s*-\s*\d+",
        r"полный",
        r"все\s+сезоны?",
        r"полный\s+сезон",
        r"complete",
        r"full\s+season",
        r"все\s+серии",
    ]
    return any(re.search(pattern, result_lower) for pattern in pack_patterns)


def _extract_year_from_name(name: str) -> int | None:
    """Extract year from torrent name."""
    year_patterns = [r"\[(\d{4})", r"\((\d{4})", r"\b(\d{4})\b"]

    for pattern in year_patterns:
        for match in re.findall(pattern, name):
            year = int(match)
            if 1900 <= year <= 2100:
                return year

    return None


def _is_year_match(result_name: str, expected_year: int | None, year_tolerance: int = 1) -> bool:
    """Check if result year matches expected year within tolerance."""
    if expected_year is None:
        return True

    extracted_year = _extract_year_from_name(result_name)
    if extracted_year is None:
        return True

    return abs(extracted_year - expected_year) <= year_tolerance


def _get_expected_year(
    media_details: MediaDetails | None,
    season_number: int | None,
    season_year: int | None,
) -> int | None:
    """Get expected year for filtering based on media type."""
    if not media_details:
        return None

    if season_number is not None and media_details.is_series:
        return parse_year(season_year) if season_year else parse_year(media_details.year)
    if not media_details.is_series:
        return parse_year(media_details.year)

    return None


def _should_skip_result(
    result: MovieSearchResult,
    result_name: str,
    provider_name: str,
    media_details: MediaDetails | None,
    season_number: int | None,
    expected_year: int | None,
    expected_titles: list[str],
) -> tuple[bool, str | None]:
    """Check if result should be skipped and return skip reason if so."""
    if not result.seeds:
        return True, "no_seeds"

    if not result.video_quality:
        result.video_quality = parse_video_quality(result_name)

    if not _has_video_markers(result_name) and _is_audio_release(result_name):
        return True, "audio_release"

    if _is_disc_image(result_name):
        return True, "disc_image"

    if _has_multiple_resolutions(result_name):
        return True, "multiple_resolutions"

    if _has_multiple_video_tracks(result_name):
        return True, "multiple_video_tracks"

    if (
        result.video_quality is None or result.video_quality == "Unknown"
    ) and not _has_video_markers(result_name):
        return True, "unknown_quality"

    if _is_season_pack(result_name, season_number):
        return True, "season_pack"

    if season_number is not None and not is_season_match(result_name, season_number):
        return True, "season_mismatch"

    if expected_year is not None and not _is_year_match(result_name, expected_year):
        return True, "year_mismatch"

    if expected_titles and not _is_fuzzy_match(result_name, expected_titles):
        return True, "title_mismatch"

    return False, None


def _filter_and_process_results(
    raw_results: list[MovieSearchResult],
    media_details: MediaDetails | None,
    season_number: int | None,
    season_year: int | None = None,
) -> list[MovieSearchResult]:
    """Filter and process raw torrent search results."""
    seen_movie_ids = set()
    results = []
    quality_counter: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    provider_stats: dict[str, dict] = {}

    expected_titles = []
    if media_details:
        expected_titles = [t for t in [media_details.title, media_details.original_title] if t]

    expected_year = _get_expected_year(media_details, season_number, season_year)

    for result in raw_results:
        result_name = result.search_name or result.name
        provider_name = result.provider_name or "unknown"

        if provider_name not in provider_stats:
            provider_stats[provider_name] = {
                "raw_count": 0,
                "filtered_count": 0,
                "accepted_count": 0,
                "total_seeds": 0,
                "skip_reasons": Counter(),
            }

        provider_stats[provider_name]["raw_count"] += 1

        if result.id in seen_movie_ids:
            skip_reasons["duplicate"] += 1
            provider_stats[provider_name]["skip_reasons"]["duplicate"] += 1
            provider_stats[provider_name]["filtered_count"] += 1
            continue

        should_skip, reason = _should_skip_result(
            result,
            result_name,
            provider_name,
            media_details,
            season_number,
            expected_year,
            expected_titles,
        )

        if should_skip:
            if reason:
                skip_reasons[reason] += 1
                provider_stats[provider_name]["skip_reasons"][reason] += 1
                logger.debug(
                    f"Filtered as {reason}",
                    name=result_name,
                    provider=provider_name,
                    season_number=season_number
                    if reason == "season_pack" or reason == "season_mismatch"
                    else None,
                    expected_year=expected_year if reason == "year_mismatch" else None,
                )
            provider_stats[provider_name]["filtered_count"] += 1
            continue

        seen_movie_ids.add(result.id)
        results.append(result)
        quality_counter[result.video_quality or "Unknown"] += 1
        provider_stats[provider_name]["accepted_count"] += 1
        if result.seeds:
            provider_stats[provider_name]["total_seeds"] += result.seeds

    _log_quality_stats(quality_counter, len(raw_results), len(results))
    _log_provider_stats(provider_stats)

    if skip_reasons:
        filter_logger = logger.bind(component="utility", operation="filter_results")
        filter_logger.info("Skip reasons", skip_reasons=dict(skip_reasons.most_common()))

    return results


def _log_quality_stats(quality_counter: Counter[str], total_raw: int, total_filtered: int) -> None:
    """Log statistics about found video qualities."""
    quality_logger = logger.bind(component="utility", operation="quality_stats")
    if not quality_counter:
        quality_logger.info(
            "No torrents found after filtering", total_raw=total_raw, total_filtered=0
        )
        return

    quality_logger.info(
        "Quality stats",
        total_raw=total_raw,
        total_filtered=total_filtered,
        quality_distribution=dict(quality_counter.most_common()),
    )


def _log_provider_stats(provider_stats: dict[str, dict]) -> None:
    """Log per-provider statistics for filtering and quality metrics."""
    provider_logger = logger.bind(component="utility", operation="filter_results")

    for provider_name, stats in provider_stats.items():
        accepted_count = stats["accepted_count"]
        avg_seeds = stats["total_seeds"] / accepted_count if accepted_count > 0 else 0.0

        provider_logger.info(
            "Provider stats",
            provider=provider_name,
            raw_count=stats["raw_count"],
            filtered_count=stats["filtered_count"],
            accepted_count=accepted_count,
            avg_seeds=round(avg_seeds, 2),
            total_seeds=stats["total_seeds"],
            skip_reasons=dict(stats["skip_reasons"].most_common()),
        )


def _log_final_results_stats(results: list[MovieSearchResult]) -> None:
    """Log statistics about final results after grouping, per provider."""
    if not results:
        return

    final_logger = logger.bind(component="utility", operation="torrent_search")
    provider_counts: dict[str, int] = Counter()
    provider_seeds: dict[str, list[int]] = {}

    for result in results:
        provider_name = result.provider_name or "unknown"
        provider_counts[provider_name] += 1

        if provider_name not in provider_seeds:
            provider_seeds[provider_name] = []

        if result.seeds:
            provider_seeds[provider_name].append(result.seeds)

    for provider_name, count in provider_counts.items():
        seeds_list = provider_seeds.get(provider_name, [])
        avg_seeds = sum(seeds_list) / len(seeds_list) if seeds_list else 0.0

        final_logger.info(
            "Final results per provider",
            provider=provider_name,
            count=count,
            avg_seeds=round(avg_seeds, 2),
            min_seeds=min(seeds_list) if seeds_list else 0,
            max_seeds=max(seeds_list) if seeds_list else 0,
        )


def _is_fuzzy_match(result_name: str, expected_titles: list[str]) -> bool:
    """Check if result name matches expected titles with strict matching.

    Does NOT match if expected title is just a substring of a longer title
    (e.g., "friends" in "smiling friends").
    """
    result_clean = clean_title_for_query(result_name).lower()

    for expected in expected_titles:
        expected_clean = clean_title_for_query(expected).lower()

        prefixes = ["сезон", "season", "s"]
        result_without_prefix = result_clean
        for prefix in prefixes:
            prefix_pattern = rf"^{re.escape(prefix)}\s*\d+"
            if re.match(prefix_pattern, result_clean):
                result_without_prefix = re.sub(prefix_pattern, "", result_clean).strip()
                break

        if result_without_prefix.startswith(expected_clean):
            return True

        main_title_match = re.match(r"^([^:\-/\|]+)", result_without_prefix)
        if main_title_match:
            main_title = main_title_match.group(1).strip()

            if main_title.startswith(expected_clean):
                return True

            expected_words = expected_clean.split()
            main_title_words = main_title.split()
            if (
                len(main_title_words) >= len(expected_words)
                and main_title_words[: len(expected_words)] == expected_words
            ):
                return True

        sections = re.split(r"\s*[/:]\s*", result_clean, maxsplit=1)
        if sections:
            first_section = sections[0].strip()
            if first_section.startswith(expected_clean):
                return True

            expected_words = expected_clean.split()
            first_section_words = first_section.split()
            if (
                len(first_section_words) >= len(expected_words)
                and first_section_words[: len(expected_words)] == expected_words
            ):
                return True

        expected_words = expected_clean.split()
        if expected_words:
            words_pattern = r"\s*[:\-/\|]\s*".join(re.escape(word) for word in expected_words)
            if re.search(words_pattern, result_clean):
                return True

        if calculate_similarity(expected, result_name) > 0.8:
            return True

    return False


def _get_quality_priority(quality: VideoQuality | str | None) -> int:
    """Get priority for quality sorting (lower = better quality)."""
    if quality is None:
        return 999

    if isinstance(quality, VideoQuality):
        return quality.priority

    if isinstance(quality, str):
        try:
            return VideoQuality(quality).priority
        except ValueError:
            return 999

    return 999


def _sort_and_group_results(
    results: list[MovieSearchResult],
) -> list[MovieSearchResult]:
    """Group by quality, select best (max seeds) per quality, sort by priority."""

    def quality_key(r: MovieSearchResult) -> str:
        q = r.video_quality
        if isinstance(q, VideoQuality):
            return q.value
        return str(q).strip() if q else "N/A"

    results.sort(key=quality_key)
    best = [
        max(group, key=lambda r: r.seeds or -1) for _, group in groupby(results, key=quality_key)
    ]
    best.sort(key=lambda r: _get_quality_priority(r.video_quality))
    return best


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
        buttons.append(
            [
                InlineKeyboardButton(
                    text=back_button_text or "Назад", callback_data=back_callback_key
                )
            ]
        )

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
    rating_emoji = _get_quality_rating_emoji(result.video_quality)

    label = f"{rating_emoji}{quality} | {size} | ⬆️{seeds} ⬇️{peers}"

    payload = {
        "action": MOVIE_DETAILED_CALLBACK,
        "movie_id": result.id,
        "results_cache_key": results_cache_key,
    }

    if result.provider_name:
        payload["provider_name"] = result.provider_name
    else:
        logger.bind(component="utility", operation="filter_results").warning(
            "MovieSearchResult missing provider_name",
            movie_id=result.id,
            name=result.name[:50] if result.name else "unknown",
        )

    if media_details:
        parsed_year = parse_year(media_details.year)
        payload["tmdb_info"] = {
            "original_title": media_details.original_title,
            "year": parsed_year,
            "quality": result.video_quality,
        }
        if season_number is not None and media_details.is_series:
            payload["tmdb_info"]["season"] = season_number

    payload["movie_details"] = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    callback_data = redis_callback_save(payload)
    return [InlineKeyboardButton(text=label, callback_data=callback_data)]


def _get_quality_rating_emoji(quality: VideoQuality | str | None) -> str:
    """Get rating emoji for quality."""
    if quality is None:
        return ""

    if isinstance(quality, VideoQuality):
        return quality.rating_emoji + " "

    if isinstance(quality, str):
        try:
            return VideoQuality(quality).rating_emoji + " "
        except ValueError:
            pass

    return ""
