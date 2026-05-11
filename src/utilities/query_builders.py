"""Build torrent search queries per provider syntax.

Kinozal accepts ``(a|b)`` alternation in ``s=``. Rutracker treats
``()``/``|`` as literals in ``nm=`` and returns 500 on noisy input — so
its provider builds flat queries instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utilities.media_utils import clean_title_for_query, parse_year

if TYPE_CHECKING:
    from models.search_provider_types import MediaDetails


def _clean_titles(media_details: MediaDetails) -> list[str]:
    """Return cleaned, deduplicated title variants in stable order."""
    titles: list[str] = []
    for raw in (media_details.title, media_details.original_title):
        if not raw:
            continue
        cleaned = clean_title_for_query(raw)
        if cleaned and cleaned not in titles:
            titles.append(cleaned)
    return titles


def _season_words(season_number: int) -> list[str]:
    """Common Russian/English season tokens used on these trackers."""
    return [
        f"сезон {season_number}",
        f"season {season_number}",
        f"S{season_number:02d}",
    ]


def _year_range(year: int | str | None) -> list[int]:
    """Return (year-1, year, year+1), clipped to plausible release years."""
    parsed = parse_year(year)
    if parsed is None:
        return []
    return [y for y in (parsed - 1, parsed, parsed + 1) if 1900 <= y <= 2100]


def _dedupe(queries: list[str], *, max_length: int | None = None) -> list[str]:
    """Drop empties, duplicates and over-length queries; keep order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in queries:
        q = raw.strip()
        if not q or q in seen:
            continue
        if max_length is not None and len(q) > max_length:
            continue
        seen.add(q)
        out.append(q)
    return out


def build_expressive_queries(
    media_details: MediaDetails,
    *,
    season_number: int | None,
    season_year: int | None,
    season_pack_only: bool,
    max_length: int | None = None,
) -> list[str]:
    """Queries for trackers that understand ``(a|b)`` alternation."""
    titles = _clean_titles(media_details)
    if not titles:
        return []

    queries: list[str] = []
    targets_specific_season = (
        season_number is not None and media_details.is_series and not season_pack_only
    )

    if targets_specific_season:
        season_alt = "|".join(_season_words(season_number))
        for t in titles:
            queries.append(f"{t} ({season_alt})")

        year_to_use = season_year if season_year is not None else media_details.year
        year_range = _year_range(year_to_use)
        if year_range:
            year_alt = " | ".join(str(y) for y in year_range)
            for t in titles:
                queries.append(f"{t} ({season_alt}) ({year_alt})")
            parsed_year = parse_year(year_to_use)
            if len(titles) > 1 and parsed_year is not None:
                combined = "|".join(sorted(titles))
                queries.append(f"({combined}) + ({season_alt}) + ({parsed_year})")
        return _dedupe(queries, max_length=max_length)

    year_range = _year_range(media_details.year)
    if not year_range:
        return _dedupe(titles, max_length=max_length)

    year_alt = " | ".join(str(y) for y in year_range)
    for t in titles:
        queries.append(f"{t} {year_alt}")
    if len(titles) > 1:
        combined = "|".join(sorted(titles))
        queries.append(f"({combined}) + ({year_alt})")
    return _dedupe(queries, max_length=max_length)


def build_flat_queries(
    media_details: MediaDetails,
    *,
    season_number: int | None,
    season_year: int | None,
    season_pack_only: bool,
    max_length: int | None = None,
) -> list[str]:
    """Plain ``title tokens`` queries for trackers without alternation."""
    titles = _clean_titles(media_details)
    if not titles:
        return []

    queries: list[str] = []
    targets_specific_season = (
        season_number is not None and media_details.is_series and not season_pack_only
    )

    if targets_specific_season:
        for t in titles:
            for season_word in _season_words(season_number):
                queries.append(f"{t} {season_word}")
        year_to_use = season_year if season_year is not None else media_details.year
        parsed_year = parse_year(year_to_use)
        if parsed_year is not None:
            for t in titles:
                queries.append(f"{t} S{season_number:02d} {parsed_year}")
        return _dedupe(queries, max_length=max_length)

    parsed_year = parse_year(media_details.year)
    for t in titles:
        queries.append(f"{t} {parsed_year}" if parsed_year is not None else t)
    return _dedupe(queries, max_length=max_length)


__all__ = ["build_expressive_queries", "build_flat_queries"]
