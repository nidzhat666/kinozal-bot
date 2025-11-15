from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from custom_types.movie_detail_service_types import MovieDetails, MovieSearchResult


class DownloadResult(TypedDict):
    file_path: str
    filename: str


@runtime_checkable
class TorrentDetailServiceProtocol(Protocol):
    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Fetch detailed information about the movie or torrent item."""


@runtime_checkable
class TorrentDownloadServiceProtocol(Protocol):
    async def download_movie(self) -> DownloadResult:
        """Download the torrent file and return its metadata."""


@runtime_checkable
class TorrentProviderProtocol(Protocol):
    name: str

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        """Search for torrents matching the provided query."""

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Fetch detailed information about the movie or torrent item."""

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download the torrent file and return its metadata."""


