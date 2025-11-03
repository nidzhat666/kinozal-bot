from typing import Optional

from pydantic import BaseModel


class MovieRatings(BaseModel):
    imdb: str = "-"
    kinopoisk: str = "-"


class TorrentDetails(BaseModel):
    key: str
    value: str | None = None


class MovieDetails(BaseModel):
    name: str
    year: str
    genres: list[str]
    director: str
    actors: list[str]
    image_url: str
    ratings: MovieRatings
    torrent_details: list[TorrentDetails]
