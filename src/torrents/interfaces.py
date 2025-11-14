from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from custom_types.movie_detail_service_types import MovieDetails


class DownloadResult(TypedDict):
    file_path: str
    filename: str


class SearchResult(TypedDict, total=False):
    id: str
    name: str
    size: str


@runtime_checkable
class TorrentSearchServiceProtocol(Protocol):
    async def search(self, query: str, quality: str | int) -> list[SearchResult]:
        """Search for torrents by query and quality."""


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

    async def search(self, query: str, quality: str | int) -> list[SearchResult]:
        """Search for torrents by query and quality."""

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Fetch detailed information about the movie or torrent item."""

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download the torrent file and return its metadata."""


