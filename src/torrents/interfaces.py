from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from models.movie_detail_service_types import MovieDetails, MovieSearchResult


class DownloadResult:
    def __init__(
        self,
        *,
        file_path: str | None = None,
        filename: str | None = None,
        magnet_link: str | None = None
    ) -> None:
        self.file_path = file_path
        self.filename = filename
        self.magnet_link = magnet_link



class TorrentProviderProtocol(Protocol):
    """Protocol for torrent provider implementations.
    
    All torrent providers must implement this interface to ensure
    compatibility with the bot's torrent search and download system.
    """
    name: str
    base_url: str
    max_query_length: int | None
    requires_authentication: bool

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

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on the tracker.
        
        Args:
            movie_id: The torrent ID on the tracker
            
        Returns:
            Full URL to the torrent page
        """
        ...
