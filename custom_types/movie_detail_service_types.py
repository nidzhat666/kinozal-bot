from typing import TypedDict, List, Tuple, Optional


class MovieRatings(TypedDict, total=False):
    imdb: str
    kinopoisk: str


class TorrentDetails(TypedDict):
    key: str
    value: Optional[str]


class MovieDetails(TypedDict):
    name: str
    year: str
    genres: str
    director: str
    actors: List[str]
    image_url: str
    ratings: MovieRatings
    torrent_details: List[Tuple[str, Optional[str]]]
