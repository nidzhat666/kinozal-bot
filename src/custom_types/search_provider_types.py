from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Provider(str, Enum):
    KINOPOISK = "kinopoisk"
    TMDB = "tmdb"


class MediaItem(BaseModel):
    provider_id: str
    provider: Provider
    title: str
    original_title: str | None = None
    year: int | None = None
    poster_url: str | None = None
    is_series: bool = False


class SeasonDetails(BaseModel):
    season_number: int
    year: int | None = None
    episodes_count: int | None = None


class MediaDetails(MediaItem):
    description: str | None = None
    seasons: list[SeasonDetails] = Field(default_factory=list)


class SearchResults(BaseModel):
    results: list[MediaItem] = Field(default_factory=list)


__all__ = [
    "Provider",
    "MediaItem",
    "MediaDetails",
    "SeasonDetails",
    "SearchResults",
]
