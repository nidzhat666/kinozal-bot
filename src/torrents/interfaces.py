from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from models.movie_detail_service_types import MovieDetails, MovieSearchResult


class DownloadResult:
    def __init__(self, *, file_path: str, filename: str) -> None:
        self.file_path = file_path
        self.filename = filename


class TorrentProviderProtocol(Protocol):
    name: str

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]: ...

    @abstractmethod
    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails: ...

    @abstractmethod
    async def download_movie(self, movie_id: int | str) -> DownloadResult: ...
