from pydantic import BaseModel, ConfigDict, Field


class MovieRatings(BaseModel):
    imdb: str = "-"
    kinopoisk: str = "-"


class TorrentDetails(BaseModel):
    key: str
    value: str | None = None

class AudioLanguage(BaseModel):
    language: str # RUS, ENG, UKR, ...
    quality: str # DUB, SUB, Original, ...

class MovieDetails(BaseModel):
    name: str
    year: str
    genres: list[str]
    director: str
    actors: list[str]
    season: int | None = None
    image_url: str | None = None
    video_quality: str | None = None
    audio_quality: str | None = None
    audio_language: list[AudioLanguage] | None = []
    ratings: MovieRatings
    torrent_details: list[TorrentDetails]


class MovieSearchResult(MovieDetails):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="movie_id")
    size: str
    search_name: str | None = None
    seeds: int | None = None
    peers: int | None = None
    has_full_details: bool = False

    @classmethod
    def from_search_data(
        cls,
        *,
        search_id: str,
        size: str,
        search_name: str,
        details: MovieDetails,
        seeds: int | None = None,
        peers: int | None = None,
        has_full_details: bool = False,
    ) -> "MovieSearchResult":
        return cls(
            movie_id=str(search_id),
            size=size,
            search_name=search_name,
            seeds=seeds,
            peers=peers,
            has_full_details=has_full_details,
            **details.model_dump(),
        )
