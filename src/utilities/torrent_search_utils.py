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
from torrents import get_active_providers
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

    active_providers = get_active_providers()
    if not active_providers:
        target_message = callback_query.message if callback_query else message
        await target_message.edit_text("Нет активных торрент-провайдеров. Проверьте настройки.")
        return

    logger.info("Searching in %d active providers: %s", len(active_providers), [p.name for p in active_providers])
    target_message = callback_query.message if callback_query else message

    # Create tasks: for each query, search in all active providers
    # Store provider and query info with each task to track results by provider
    tasks_with_info = [
        (provider, q, provider.search(
            q,
            requested_item=requested_item,
            requested_type=requested_type,
        ))
        for q in queries
        for provider in active_providers
    ]
    
    tasks = [task for _, _, task in tasks_with_info]

    try:
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        raw_results = []
        provider_stats: dict[str, int] = {}
        
        for (provider, query, _), res in zip(tasks_with_info, results_list):
            provider_name = provider.name
            if isinstance(res, Exception):
                logger.warning(
                    "[%s] Search failed for query '%s': %s",
                    provider_name,
                    query,
                    res
                )
                provider_stats[provider_name] = provider_stats.get(provider_name, 0)
            elif isinstance(res, list):
                count = len(res)
                provider_stats[provider_name] = provider_stats.get(provider_name, 0) + count
                raw_results.extend(res)
                logger.info(
                    "[%s] Found %d torrents for query '%s'",
                    provider_name,
                    count,
                    query
                )
        
        # Log total stats per provider
        for provider_name, total_count in provider_stats.items():
            logger.info(
                "[%s] Total results across all queries: %d torrents",
                provider_name,
                total_count
            )

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


def _is_audio_release(result_name: str) -> bool:
    """Check if result is an audio release (soundtrack, OST, MP3, FLAC, etc.).
    
    Returns True if the result name contains audio-related keywords.
    Strictly filters out audio packs, audio tracks, and audio-only releases.
    """
    result_lower = result_name.lower()
    
    # Hard filters - always skip if these appear
    hard_audio_keywords = [
        "audio pack",
        "[audio pack]",
        "аудиодорож",
        "озвучк",
        "soundtrack",
        "ost",
        "mp3",
        "flac",
        "score",
        "albums",
        "album",
        "tracks",
        "track",
        "lossless",
        "аудио",
        "саундтрек",
        "музыка",
    ]
    
    # Check hard filters first
    for keyword in hard_audio_keywords:
        if keyword in result_lower:
            return True
    
    # Check AC3/DTS without video markers (audio-only, not video with AC3/DTS audio track)
    audio_codecs = ["ac3", "dts"]
    has_audio_codec = any(codec in result_lower for codec in audio_codecs)
    
    if has_audio_codec:
        # Check if there are video markers - if not, it's likely audio-only
        video_markers = [
            "1080p", "2160p", "720p", "480p", "576p",
            "bdrip", "bd-rip", "bluray", "blu-ray",
            "web-dl", "webdl", "webrip", "web-rip",
            "hdrip", "hd-rip", "dvdrip", "dvd-rip",
            "remux", "uhd", "4k", "hdr", "hevc", "x265", "x264",
        ]
        has_video_marker = any(marker in result_lower for marker in video_markers)
        
        if not has_video_marker:
            return True
    
    return False


def _is_disc_image(result_name: str) -> bool:
    """Check if result is a disc image (DVD9, DVD-5, NTSC, PAL, etc.).
    
    Returns True if the result name indicates a disc image format.
    These are typically not useful for streaming/downloading.
    """
    result_lower = result_name.lower()
    
    # Disc image indicators
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
    
    for keyword in disc_keywords:
        if keyword in result_lower:
            return True
    
    return False


def _has_video_markers(result_name: str) -> bool:
    """Check if result name contains explicit video quality markers.
    
    Returns True if the name contains indicators of video quality/resolution.
    Used to filter out Unknown quality results that are likely not video.
    """
    result_lower = result_name.lower()
    
    # Video quality markers that indicate this is actually a video release
    video_markers = [
        # Resolutions
        "1080p", "2160p", "720p", "480p", "576p", "1080i",
        # Source types
        "bdrip", "bd-rip", "bluray", "blu-ray", "blu ray",
        "web-dl", "webdl", "webrip", "web-rip", "web dl",
        "hdrip", "hd-rip", "hd rip",
        "dvdrip", "dvd-rip", "dvd rip",
        "remux", "bdremux", "bd-remux",
        # Quality indicators
        "uhd", "4k",
        "hdr", "hdr10", "hdr10+",
        "dolby vision", "dovi", "dv",
        # Codecs (video)
        "hevc", "x265", "h265",
        "x264", "h264", "avc",
    ]
    
    for marker in video_markers:
        if marker in result_lower:
            return True
    
    return False


def _has_multiple_resolutions(result_name: str) -> bool:
    """Check if result name contains multiple video resolutions (e.g., both 1080p and 720p).
    
    Returns True if the name contains multiple resolution indicators that indicate
    the release contains multiple video tracks in one file.
    Examples: "WEB-DL HD (1080p, 720p)", "1080p + 720p", etc.
    """
    result_lower = result_name.lower()
    
    # Common resolution patterns
    resolutions = {
        "1080p": r"\b1080p\b",
        "720p": r"\b720p\b",
        "2160p": r"\b2160p\b",
        "4k": r"\b4k\b",
        "480p": r"\b480p\b",
        "576p": r"\b576p\b",
    }
    
    found_resolutions = []
    for res_name, pattern in resolutions.items():
        if re.search(pattern, result_lower):
            found_resolutions.append(res_name)
    
    # Filter out if multiple resolutions found (especially 1080p + 720p combination)
    if len(found_resolutions) > 1:
        # Specifically filter out 1080p + 720p combinations
        if "1080p" in found_resolutions and "720p" in found_resolutions:
            return True
    
    return False


def _has_multiple_video_tracks(result_name: str) -> bool:
    """Check if result name indicates multiple video tracks in one file.
    
    Returns True if the name contains indicators of multiple video tracks.
    Examples: "2 видео", "2 video", "dual video", "multiple video tracks", etc.
    """
    result_lower = result_name.lower()
    
    # Patterns that indicate multiple video tracks
    multiple_track_patterns = [
        r"\d+\s+видео",  # "2 видео", "две видео"
        r"\d+\s+video",  # "2 video", "dual video"
        r"dual\s+video",  # "dual video"
        r"multiple\s+video",  # "multiple video"
        r"двойное\s+видео",  # "двойное видео"
        r"две\s+видеодорожки",  # "две видеодорожки"
        r"2\s+видеодорожки",  # "2 видеодорожки"
        r"видеодорожки\s*\d+",  # "видеодорожки 2"
        r"video\s+tracks?\s*\d+",  # "video tracks 2"
        r"\d+\s+video\s+tracks?",  # "2 video tracks"
    ]
    
    for pattern in multiple_track_patterns:
        if re.search(pattern, result_lower):
            return True
    
    return False


def _is_season_pack(result_name: str, target_season: int | None) -> bool:
    """Check if result is a season pack (multiple seasons bundled together).
    
    Returns True if the result name indicates multiple seasons (e.g., "1-2 сезон", "S01-S02").
    Only checks when target_season is specified (i.e., we're looking for a specific season).
    """
    if target_season is None:
        return False
    
    result_lower = result_name.lower()
    
    # Patterns that indicate multiple seasons
    # Examples: "1-2 сезон", "S01-S02", "сезоны 1-4", "полный", "все сезоны"
    # Also handles cases like "(1-2 сезон: 1-17 серии из 17)"
    pack_patterns = [
        r"\d+\s*-\s*\d+\s*сезон",  # "1-2 сезон", "1-4 сезон", "(1-2 сезон: ...)"
        r"\d+\s*-\s*\d+\s*сезоны",  # "1-2 сезоны" (plural)
        r"s\d+\s*-\s*s\d+",  # "S01-S02", "S1-S4"
        r"s\d+\s*-\s*\d+",  # "S01-02" (alternative format)
        r"\d+\s*-\s*s\d+",  # "1-S02" (alternative format)
        r"сезоны?\s*\d+\s*-\s*\d+",  # "сезоны 1-4", "сезон 1-2"
        r"полный",  # "полный"
        r"все\s+сезоны?",  # "все сезоны"
        r"полный\s+сезон",  # "полный сезон"
        r"complete",  # "complete"
        r"full\s+season",  # "full season"
        r"все\s+серии",  # "все серии"
    ]
    
    for pattern in pack_patterns:
        if re.search(pattern, result_lower):
            return True
    
    return False


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

        provider_name = result.provider_name or "unknown"
        
        # Filter out audio releases (soundtracks, OST, MP3, FLAC, audio pack, etc.)
        if _is_audio_release(result_name):
            skip_reasons["audio_release"] += 1
            logger.info(
                "[%s] SKIP audio_release: [%s] %s",
                provider_name,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue
        
        # Filter out disc images (DVD9, DVD-5, NTSC, PAL, etc.)
        if _is_disc_image(result_name):
            skip_reasons["disc_image"] += 1
            logger.info(
                "[%s] SKIP disc_image: [%s] %s",
                provider_name,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue
        
        # Filter out releases with multiple resolutions (e.g., 1080p + 720p in one file)
        if _has_multiple_resolutions(result_name):
            skip_reasons["multiple_resolutions"] += 1
            logger.info(
                "[%s] SKIP multiple_resolutions: [%s] %s",
                provider_name,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue
        
        # Filter out releases with multiple video tracks
        if _has_multiple_video_tracks(result_name):
            skip_reasons["multiple_video_tracks"] += 1
            logger.info(
                "[%s] SKIP multiple_video_tracks: [%s] %s",
                provider_name,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue
        
        # Filter out Unknown quality results that don't have video markers
        if result.video_quality is None or result.video_quality == "Unknown":
            if not _has_video_markers(result_name):
                skip_reasons["unknown_quality"] += 1
                logger.info(
                    "[%s] SKIP unknown_quality (no video markers): [%s] %s",
                    provider_name,
                    result.video_quality or "N/A",
                    result_name[:80],
                )
                continue
        
        # Filter out season packs when looking for a specific season
        if _is_season_pack(result_name, season_number):
            skip_reasons["season_pack"] += 1
            logger.info(
                "[%s] SKIP season_pack (S%02d): [%s] %s",
                provider_name,
                season_number,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue
        
        if season_number is not None and not is_season_match(
            result_name, season_number
        ):
            skip_reasons["season_mismatch"] += 1
            logger.info(
                "[%s] SKIP season_mismatch (S%02d): [%s] %s",
                provider_name,
                season_number,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue

        if expected_titles and not _is_fuzzy_match(result_name, expected_titles):
            skip_reasons["title_mismatch"] += 1
            logger.info(
                "[%s] SKIP title_mismatch: [%s] %s",
                provider_name,
                result.video_quality or "N/A",
                result_name[:80],
            )
            continue

        seen_movie_ids.add(result.id)
        results.append(result)
        quality_counter[result.video_quality or "Unknown"] += 1
        logger.info(
            "[%s] ACCEPTED: [%s] seeds=%s %s",
            provider_name,
            result.video_quality or "N/A",
            result.seeds,
            result_name,
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


def _get_quality_priority(quality: VideoQuality | str | None) -> int:
    """Get priority for quality sorting (lower = better quality).
    
    Returns priority from VideoQuality enum if quality is recognized,
    otherwise returns high priority (999) for unknown qualities.
    """
    if quality is None:
        return 999
    
    # If already VideoQuality enum, use priority directly
    if isinstance(quality, VideoQuality):
        return quality.priority
    
    # If string, try to convert to VideoQuality
    if isinstance(quality, str):
        try:
            video_quality = VideoQuality(quality)
            return video_quality.priority
        except ValueError:
            # Unknown quality string
            return 999
    
    return 999


def _sort_and_group_results(
    results: list[MovieSearchResult],
) -> list[MovieSearchResult]:
    """Group results by quality and select best (max seeds) from each group.
    
    Then sort final results by quality priority (lower priority = better quality).
    """
    def get_quality_key(r: MovieSearchResult) -> str:
        """Get quality as string for grouping."""
        return r.video_quality or "N/A"

    # Sort by quality for grouping
    results.sort(key=get_quality_key)
    best_results = []

    # Group by quality and select best (max seeds) from each group
    for _, group in groupby(results, key=get_quality_key):
        group_list = list(group)
        best_in_group = max(
            group_list, 
            key=lambda r: r.seeds if r.seeds is not None else -1
        )
        best_results.append(best_in_group)

    # Sort final results by quality priority (lower = better)
    best_results.sort(
        key=lambda r: _get_quality_priority(r.video_quality)
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
    
    # Always include provider_name (should always be set by providers)
    # This ensures we use the correct provider when fetching details
    if result.provider_name:
        payload["provider_name"] = result.provider_name
    else:
        logger.warning(
            "MovieSearchResult missing provider_name for movie ID: %s, name: %s",
            result.id,
            result.name[:50] if result.name else "unknown"
        )
    
    if media_details:
        payload["tmdb_info"] = {
            "original_title": media_details.original_title,
            "year": media_details.year,
            "quality": result.video_quality,
        }
        if season_number is not None and media_details.is_series:
            payload["tmdb_info"]["season"] = season_number
    
    # Always include movie_details in callback_data to avoid refetching
    # This allows the handler to use cached data when available
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
