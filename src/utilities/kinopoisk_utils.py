from __future__ import annotations

from custom_types.kinopoisk_types import (
    KinopoiskMovieBase,
    KinopoiskSeasonInfo,
)


def get_preferred_title(movie: KinopoiskMovieBase) -> str:
    """
    Returns the most suitable title to display for a Kinopoisk movie.
    Preference order: localized name -> alternative name -> English name -> any alias.
    """
    return movie.alternative_name



def format_button_caption(movie: KinopoiskMovieBase) -> str:
    """Builds a caption using the first two titles from the alias list."""

    segments: list[str] = list(filter(None, [movie.name or None, movie.alternative_name]))

    if movie.year:
        segments.append(str(movie.year))

    movie_type = ("сериал" if movie.is_series else "фильм")
    segments.append(movie_type)

    return " / ".join(segments)


def build_torrent_query(
    movie: KinopoiskMovieBase,
    *,
    season_number: int | None = None,
    season_year: int | None = None,
    include_year_for_movie: bool = True,
) -> str:
    """
    Constructs a search query for torrents using Kinopoisk metadata.

    For series the query will follow the pattern "<title> <season> сезон".
    If season_year is provided it will be appended as well.
    If no season is supplied and include_year_for_movie is True, the series'
    release year will be appended (to disambiguate remakes). Movies are searched
    by title only.
    """
    title = get_preferred_title(movie)
    parts = [title]

    if season_number is not None:
        parts.append(f"{season_number} сезон")
        if season_year:
            parts.append(str(season_year))
    elif include_year_for_movie and movie.is_series and movie.year:
        parts.append(str(movie.year))

    return " ".join(part for part in parts if part).strip()


def extract_available_seasons(
    seasons: list[KinopoiskSeasonInfo] | None,
) -> list[int]:
    """
    Returns a sorted list of available season numbers, ignoring non-positive values.
    """
    if not seasons:
        return []
    unique_numbers = {season.number for season in seasons if season.number and season.number > 0}
    return sorted(unique_numbers)


__all__ = [
    "build_torrent_query",
    "extract_available_seasons",
    "format_button_caption",
    "get_preferred_title",
]

