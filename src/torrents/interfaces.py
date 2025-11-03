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
class TorrentAuthServiceProtocol(Protocol):
    async def authenticate(self) -> dict[str, str]:
        """Return auth data that can be used by download services."""


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

    def get_auth_service(self) -> TorrentAuthServiceProtocol | None:
        """Return an auth service for the provider or None if not required."""

    def get_search_service(self) -> TorrentSearchServiceProtocol:
        """Return a search service instance for the provider."""

    def get_detail_service(self) -> TorrentDetailServiceProtocol:
        """Return a detail service instance for the provider."""

    def get_download_service(
        self, movie_id: int | str, auth_data: dict[str, str] | None = None
    ) -> TorrentDownloadServiceProtocol:
        """Return a download service instance for the provider."""


