from __future__ import annotations

from custom_types.search_provider_types import MediaDetails


def build_torrent_query_from_media_details(
    media_details: MediaDetails,
    season_number: int | None = None,
    season_year: int | None = None,
) -> str:
    title = media_details.original_title or media_details.title
    year = media_details.year
    parts = [title]

    if media_details.is_series:
        if season_number:
            parts.append(f"сезон {season_number}")
        if season_year:
            parts.append(f"{season_year}")

    return " ".join(map(str, parts))


__all__ = [
    "build_torrent_query_from_media_details",
]

