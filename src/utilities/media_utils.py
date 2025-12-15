from __future__ import annotations

import re
from difflib import SequenceMatcher

from models.search_provider_types import MediaDetails
from models.movie_detail_service_types import VideoQuality

MAX_QUERY_LENGTH = 64


def build_torrent_query_from_media_details(
    media_details: MediaDetails,
    season_number: int | None = None,
    season_year: int | None = None,
) -> str:
    # Prepare titles
    titles = set()
    if media_details.title:
        titles.add(clean_title_for_query(media_details.title))
    if media_details.original_title:
        titles.add(clean_title_for_query(media_details.original_title))

    # We prefer the Russian title (usually stored in 'title') for single-title fallback
    # But let's keep track of them explicitly
    ru_title = (
        clean_title_for_query(media_details.title) if media_details.title else None
    )
    en_title = (
        clean_title_for_query(media_details.original_title)
        if media_details.original_title
        else None
    )

    sorted_titles = sorted(list(titles))
    if not sorted_titles:
        return ""

    # Prepare parts
    combined_titles_part = (
        f"({'|'.join(sorted_titles)})" if len(sorted_titles) > 1 else sorted_titles[0]
    )

    season_part = None
    if media_details.is_series and season_number:
        s_num = str(season_number)
        season_variants = [
            f"сезон {s_num}",
            f"season {s_num}",
            f"S{season_number:02d}",
        ]
        season_part = f"({'|'.join(season_variants)})"

    year_part = None
    if not media_details.is_series and media_details.year:
        year_part = f"({media_details.year})"

    # Strategy 1: Everything (Combined Titles + Season + Year)
    query = _construct_query(combined_titles_part, season_part, year_part)
    if len(query) <= MAX_QUERY_LENGTH:
        return query

    # Strategy 2: Combined Titles + Season (Drop Year)
    if year_part:
        query = _construct_query(combined_titles_part, season_part, None)
        if len(query) <= MAX_QUERY_LENGTH:
            return query

    # Strategy 3: Single Title (Russian preferred) + Season + Year
    # If combined was too long, try just Russian
    if ru_title:
        query = _construct_query(ru_title, season_part, year_part)
        if len(query) <= MAX_QUERY_LENGTH:
            return query

    # Strategy 4: Single Title (Russian preferred) + Season (Drop Year)
    if ru_title and year_part:
        query = _construct_query(ru_title, season_part, None)
        if len(query) <= MAX_QUERY_LENGTH:
            return query

    # Strategy 5: Single Title (English preferred if we haven't tried or if RU failed) + Season + Year
    if en_title and en_title != ru_title:
        query = _construct_query(en_title, season_part, year_part)
        if len(query) <= MAX_QUERY_LENGTH:
            return query

    # Strategy 6: Single Title (English) + Season (Drop Year)
    if en_title and en_title != ru_title and year_part:
        query = _construct_query(en_title, season_part, None)
        if len(query) <= MAX_QUERY_LENGTH:
            return query

    # Strategy 7: Truncate Title (Last resort)
    # Use the shortest available title or just truncate Russian
    target_title = ru_title or en_title or sorted_titles[0]
    # Estimate available space
    # query = title + " + " + season_part
    # space = 64 - len(season_part) - 3

    extras_len = 0
    extras_parts = []
    if season_part:
        extras_parts.append(season_part)
    # We probably dropped year already if we are here

    extras_str = " + ".join(extras_parts)
    if extras_str:
        extras_len = len(extras_str) + 3  # " + "

    available_for_title = MAX_QUERY_LENGTH - extras_len
    if (
        available_for_title < 10
    ):  # If almost no space, just return what we can, it will likely fail but better than error
        return _construct_query(target_title, season_part, None)[:MAX_QUERY_LENGTH]

    truncated_title = target_title[:available_for_title].strip()
    return _construct_query(truncated_title, season_part, None)


def _construct_query(
    title_part: str, season_part: str | None, year_part: str | None
) -> str:
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
    name_lower = name.lower()
    for quality in VideoQuality:
        if any(k in name_lower for k in quality.keywords):
            return quality
    return None


def calculate_similarity(s1: str, s2: str) -> float:
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def extract_season_number(title: str) -> int | None:
    title_lower = title.lower()

    # Patterns: "season X", "сезон X", "X сезон", "sX"
    patterns = [
        r"(?:season|сезон)\s*(\d+)",
        r"(\d+)\s*сезон",
        r"\bs(\d+)",
    ]

    for pattern in patterns:
        if match := re.search(pattern, title_lower):
            return int(match.group(1))

    return None


def is_season_match(title: str, target_season: int) -> bool:
    extracted = extract_season_number(title)
    return extracted == target_season if extracted is not None else False


__all__ = [
    "build_torrent_query_from_media_details",
    "clean_title_for_query",
    "parse_video_quality",
    "calculate_similarity",
    "extract_season_number",
    "is_season_match",
]
