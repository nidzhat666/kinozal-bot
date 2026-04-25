from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from models.movie_detail_service_types import VideoQuality
from utilities.logger_utils import get_logger

if TYPE_CHECKING:
    from models.search_provider_types import MediaDetails

logger = get_logger(__name__)

MAX_QUERY_LENGTH = 64


def build_torrent_query_from_media_details(
    media_details: MediaDetails,
    season_number: int | None = None,
    season_year: int | None = None,
    max_length: int | None = 64,
) -> str:
    titles = set()
    if media_details.title:
        titles.add(clean_title_for_query(media_details.title))
    if media_details.original_title:
        titles.add(clean_title_for_query(media_details.original_title))

    ru_title = clean_title_for_query(media_details.title) if media_details.title else None
    en_title = (
        clean_title_for_query(media_details.original_title)
        if media_details.original_title
        else None
    )

    sorted_titles = sorted(titles)
    if not sorted_titles:
        return ""

    combined_titles_part = (
        f"({'|'.join(sorted_titles)})" if len(sorted_titles) > 1 else sorted_titles[0]
    )

    season_part = None
    if media_details.is_series and season_number:
        s_num = str(season_number)
        season_variants = [f"сезон {s_num}", f"season {s_num}", f"S{season_number:02d}"]
        season_part = f"({'|'.join(season_variants)})"

    year_part = None
    if media_details.is_series and season_year:
        parsed_year = parse_year(season_year)
        if parsed_year:
            year_part = f"({parsed_year})"
    elif not media_details.is_series and media_details.year:
        year_part = f"({media_details.year})"

    if max_length is None:
        return _construct_query(combined_titles_part, season_part, year_part)

    query = _construct_query(combined_titles_part, season_part, year_part)
    if len(query) <= max_length:
        return query

    if year_part:
        query = _construct_query(combined_titles_part, season_part, None)
        if len(query) <= max_length:
            return query

    if ru_title:
        query = _construct_query(ru_title, season_part, year_part)
        if len(query) <= max_length:
            return query

    if ru_title and year_part:
        query = _construct_query(ru_title, season_part, None)
        if len(query) <= max_length:
            return query

    if en_title and en_title != ru_title:
        query = _construct_query(en_title, season_part, year_part)
        if len(query) <= max_length:
            return query

    if en_title and en_title != ru_title and year_part:
        query = _construct_query(en_title, season_part, None)
        if len(query) <= max_length:
            return query

    target_title = ru_title or en_title or sorted_titles[0]
    extras_len = len(season_part) + 3 if season_part else 0
    available_for_title = max_length - extras_len

    if available_for_title < 10:
        return _construct_query(target_title, season_part, None)[:max_length]

    truncated_title = target_title[:available_for_title].strip()
    return _construct_query(truncated_title, season_part, None)


def _construct_query(title_part: str, season_part: str | None, year_part: str | None) -> str:
    parts = [title_part]
    if season_part:
        parts.append(season_part)
    if year_part:
        parts.append(year_part)
    return " + ".join(parts)


def clean_title_for_query(title: str) -> str:
    cleaned = re.sub(r"[|^$()+]", " ", title)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_video_quality(name: str) -> str | None:
    """Parse video quality from torrent name.

    Priority order (as per requirements):
    1. BDRemux/UHD BDRemux/Remux
    2. WEB-DL/WEBRip/WEB-DLRip
    3. BDRip/BluRay
    4. HDRip/HDTVRip/TVRip
    5. DVDRip/DVD9

    Important: HDRip can NEVER be 4K HDR DV, even if HDR/DV keywords are present.
    HDR/DV are attributes/flags, not quality classes.
    """
    name_lower = name.lower()

    # Check for HDRip keyword - if present, 4K HDR DV/HDR can't match
    has_hdrip_keyword = "hdrip" in name_lower or "hd-rip" in name_lower or "hd rip" in name_lower

    # Priority order: BDRemux → WEB-DL/WEBRip → BDRip/BluRay → HDRip → DVDRip
    priority_order = [
        # REMUX variants (highest priority)
        VideoQuality.UHD_4K_REMUX,
        VideoQuality.FHD_1080P_REMUX,
        # WEB-DL/WEBRip variants (high priority)
        VideoQuality.UHD_4K_WEB,  # 4K WEB-DL (highest priority among WEB-DL)
        VideoQuality.UHD_4K_WEBRIP,  # 4K WEBRip
        VideoQuality.FHD_1080P_WEB,
        VideoQuality.HD_720P_WEB,
        VideoQuality.WEBRIP,  # WEBRip with or without resolution
        # BDRip/BluRay variants
        VideoQuality.UHD_4K_BDRIP,
        VideoQuality.FHD_1080P_BLURAY,
        VideoQuality.FHD_1080P_BDRIP,
        VideoQuality.HD_720P_BLURAY,
        VideoQuality.HD_720P_BDRIP,
        VideoQuality.BDRIP,  # Generic BDRip
        # HDRip/HDTVRip (before generic resolutions)
        VideoQuality.HDRIP,
        # Generic resolutions (check after source-based)
        VideoQuality.UHD_4K,
        VideoQuality.FHD_1080P,
        VideoQuality.HD_1080I,
        VideoQuality.HD_720P,
        VideoQuality.SD_576P,
        VideoQuality.SD_480P,
        # DVDRip (low priority)
        VideoQuality.DVDRIP,
        # 4K HDR variants (check last, and only if NOT HDRip)
        # These are treated as attributes/flags, not primary quality classes
        VideoQuality.UHD_4K_HDR_DV,  # Only if not HDRip
        VideoQuality.UHD_4K_HDR,  # Only if not HDRip
    ]

    for quality in priority_order:
        # Special handling: 4K HDR DV/HDR can't be HDRip
        if has_hdrip_keyword and quality in (
            VideoQuality.UHD_4K_HDR_DV,
            VideoQuality.UHD_4K_HDR,
        ):
            continue

        if _matches_quality_rules(name_lower, quality.match_rules):
            # Log when quality is mapped to generic "4K" or "1080p" without source specification
            # This helps identify cases where mapping might be incorrect
            if quality in (VideoQuality.UHD_4K, VideoQuality.FHD_1080P):
                op_logger = logger.bind(component="utility", operation="parse_quality")
                op_logger.warning(
                    "Generic quality detected (no source specification)",
                    quality=quality.value,
                    torrent_name=name,
                )
            return quality

    op_logger = logger.bind(component="utility", operation="parse_quality")
    op_logger.warning("Unknown video quality in torrent name", name=name)
    return None


def _matches_quality_rules(name: str, rules: list[tuple[list[str], list[str]]]) -> bool:
    """Check if name matches any of the quality rules.

    Each rule is (required_all, required_any):
    - All keywords in required_all must be present
    - At least one keyword from required_any must be present (if not empty)
    """
    for required_all, required_any in rules:
        # Check all required keywords are present
        if not all(kw in name for kw in required_all):
            continue

        # If required_any is empty, rule matches
        if not required_any:
            return True

        # Check at least one of required_any is present
        if any(kw in name for kw in required_any):
            return True

    return False


def calculate_similarity(s1: str, s2: str) -> float:
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def extract_season_number(title: str) -> int | None:
    title_lower = title.lower()
    patterns = [
        r"(\d+)\s*сезон",
        r"(?:season|сезон)\s*:?\s*(\d+)",
        r"\bs(\d+)",
    ]

    for pattern in patterns:
        if match := re.search(pattern, title_lower):
            return int(match.group(1))

    return None


def is_season_match(title: str, target_season: int) -> bool:
    extracted = extract_season_number(title)
    return extracted == target_season if extracted is not None else False


def parse_year(year: int | str | None) -> int | None:
    """Parse and validate year from various formats.

    Extracts a 4-digit year from string or returns integer year.
    Returns None if year cannot be reliably determined.

    This function ensures that non-numeric values (like director names)
    are not used as years in file naming.

    Examples:
        - "2024" -> 2024
        - "1999-2004" -> 1999
        - "Шейн Блэк" -> None
        - 2013 -> 2013
        - None -> None
    """
    if year is None:
        return None

    if isinstance(year, int):
        if 1900 <= year <= 2100:
            return year
        return None

    if isinstance(year, str):
        year_match = re.search(r"(\d{4})", str(year))
        if year_match:
            parsed_year = int(year_match.group(1))
            if 1900 <= parsed_year <= 2100:
                return parsed_year
    return None


__all__ = [
    "build_torrent_query_from_media_details",
    "calculate_similarity",
    "clean_title_for_query",
    "extract_season_number",
    "is_season_match",
    "parse_video_quality",
    "parse_year",
]
