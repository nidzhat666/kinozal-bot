from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KinopoiskName(BaseModel):
    name: str
    language: str | None = None
    type: str | None = None


class KinopoiskPoster(BaseModel):
    url: str | None = None
    preview_url: str | None = Field(default=None, alias="previewUrl")

    model_config = ConfigDict(populate_by_name=True)


class KinopoiskRating(BaseModel):
    kp: float | None = None
    imdb: float | None = None
    film_critics: float | None = Field(default=None, alias="filmCritics")
    russian_film_critics: float | None = Field(default=None, alias="russianFilmCritics")
    awaiting: float | None = Field(default=None, alias="await")

    model_config = ConfigDict(populate_by_name=True)


class KinopoiskVotes(BaseModel):
    kp: int | None = None
    imdb: int | None = None
    film_critics: int | None = Field(default=None, alias="filmCritics")
    russian_film_critics: int | None = Field(default=None, alias="russianFilmCritics")
    awaiting: int | None = Field(default=None, alias="await")

    model_config = ConfigDict(populate_by_name=True)


class KinopoiskReleaseYear(BaseModel):
    start: int | None = None
    end: int | None = None


class KinopoiskSeasonInfo(BaseModel):
    number: int
    episodes_count: int | None = Field(default=None, alias="episodesCount")

    model_config = ConfigDict(populate_by_name=True)


class KinopoiskSeason(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    number: int
    air_date: datetime | None = Field(default=None, alias="airDate")
    episodes_count: int | None = Field(default=None, alias="episodesCount")
    name: str | None = None
    en_name: str | None = Field(default=None, alias="enName")


class KinopoiskMovieBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str | None = None
    alternative_name: str | None = Field(default=None, alias="alternativeName")
    en_name: str | None = Field(default=None, alias="enName")
    type: str | None = None
    year: int | None = None
    description: str | None = None
    short_description: str | None = Field(default=None, alias="shortDescription")
    status: str | None = None
    is_series: bool = Field(default=False, alias="isSeries")
    movie_length: int | None = Field(default=None, alias="movieLength")
    series_length: int | None = Field(default=None, alias="seriesLength")
    names: list[KinopoiskName] = Field(default_factory=list)
    poster: KinopoiskPoster | None = None
    rating: KinopoiskRating | None = None
    votes: KinopoiskVotes | None = None
    release_years: list[KinopoiskReleaseYear] = Field(default_factory=list, alias="releaseYears")


class KinopoiskMovieDetails(KinopoiskMovieBase):
    seasons_info: list[KinopoiskSeasonInfo] = Field(default_factory=list, alias="seasonsInfo")


class KinopoiskSearchResponse(BaseModel):
    docs: list[KinopoiskMovieBase] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    page: int | None = None
    pages: int | None = None


class KinopoiskSeasonListResponse(BaseModel):
    docs: list[KinopoiskSeason] = Field(default_factory=list)
    total: int | None = None
    limit: int | None = None
    page: int | None = None
    pages: int | None = None


__all__ = [
    "KinopoiskMovieBase",
    "KinopoiskMovieDetails",
    "KinopoiskName",
    "KinopoiskPoster",
    "KinopoiskRating",
    "KinopoiskReleaseYear",
    "KinopoiskSearchResponse",
    "KinopoiskSeasonInfo",
    "KinopoiskSeason",
    "KinopoiskSeasonListResponse",
    "KinopoiskVotes",
]

