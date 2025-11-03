from __future__ import annotations

from torrents.interfaces import (
    TorrentAuthServiceProtocol,
    TorrentDetailServiceProtocol,
    TorrentDownloadServiceProtocol,
    TorrentProviderProtocol,
    TorrentSearchServiceProtocol,
)
from torrents.kinozal_services.kinozal_auth_service import KinozalAuthService
from torrents.kinozal_services.movie_detail_service import MovieDetailService
from torrents.kinozal_services.movie_download_service import MovieDownloadService
from torrents.kinozal_services.movie_search_service import MovieSearchService


class KinozalTorrentProvider(TorrentProviderProtocol):
    name = "kinozal"

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    def get_auth_service(self) -> TorrentAuthServiceProtocol | None:
        if not self._credentials:
            return None
        username = self._credentials.get("username")
        password = self._credentials.get("password")
        if not username or not password:
            return None
        return KinozalAuthService(username=username, password=password)

    def get_search_service(self) -> TorrentSearchServiceProtocol:
        return MovieSearchService()

    def get_detail_service(self) -> TorrentDetailServiceProtocol:
        return MovieDetailService()

    def get_download_service(
        self, movie_id: int | str, auth_data: dict[str, str] | None = None
    ) -> TorrentDownloadServiceProtocol:
        if auth_data is None:
            raise ValueError("Kinozal download service requires auth data.")
        return MovieDownloadService(movie_id, auth_data)


