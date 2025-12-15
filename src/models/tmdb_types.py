from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TmdbBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TmdbSearchResult(TmdbBase):
    id: int
    overview: str | None = None
    popularity: float | None = None
    poster_path: str | None = Field(default=None, alias="poster_path")
    backdrop_path: str | None = Field(default=None, alias="backdrop_path")
    vote_average: float | None = Field(default=None, alias="vote_average")
    vote_count: int | None = Field(default=None, alias="vote_count")
    media_type: str | None = Field(default=None, alias="media_type")


class TmdbMovieSearchResult(TmdbSearchResult):
    title: str | None = None
    original_title: str | None = Field(default=None, alias="original_title")
    release_date: date | None = Field(default=None, alias="release_date")
    media_type: str = "movie"

    @field_validator("release_date", mode="before")
    def validate_release_date(cls, v: str | None) -> str | None:
        if v == "":
            return None
        return v


class TmdbTVShowSearchResult(TmdbSearchResult):
    name: str | None = None
    original_name: str | None = Field(default=None, alias="original_name")
    first_air_date: date | None = Field(default=None, alias="first_air_date")
    media_type: str = "tv"

    @field_validator("first_air_date", mode="before")
    def validate_first_air_date(cls, v: str | None) -> str | None:
        if v == "":
            return None
        return v


class TmdbSearchResponse(TmdbBase):
    page: int
    results: list[TmdbMovieSearchResult | TmdbTVShowSearchResult] = Field(
        default_factory=list
    )
    total_pages: int = Field(alias="total_pages")
    total_results: int = Field(alias="total_results")

    @field_validator("results", mode="before")
    def validate_results(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        validated_results = []
        for item in v:
            media_type = item.get("media_type")
            if media_type == "movie":
                validated_results.append(TmdbMovieSearchResult.model_validate(item))
            elif media_type == "tv":
                validated_results.append(TmdbTVShowSearchResult.model_validate(item))
        return validated_results


class TmdbSeason(TmdbBase):
    id: int
    name: str
    overview: str | None = None
    air_date: date | None = Field(default=None, alias="air_date")
    episode_count: int = Field(alias="episode_count")
    poster_path: str | None = Field(default=None, alias="poster_path")
    season_number: int = Field(alias="season_number")


class TmdbTVShowDetails(TmdbTVShowSearchResult):
    number_of_seasons: int = Field(alias="number_of_seasons")
    number_of_episodes: int = Field(alias="number_of_episodes")
    seasons: list[TmdbSeason] = Field(default_factory=list)
    last_air_date: date | None = Field(default=None, alias="last_air_date")


class TmdbMovieDetails(TmdbMovieSearchResult):
    pass


__all__ = [
    "TmdbSearchResponse",
    "TmdbMovieSearchResult",
    "TmdbTVShowSearchResult",
    "TmdbTVShowDetails",
    "TmdbMovieDetails",
    "TmdbSeason",
]
