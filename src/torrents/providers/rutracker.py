import httpx

from bot.config import RUTRACKER_URL
from services.exceptions import RutrackerApiError
from models.movie_detail_service_types import MovieDetails, MovieSearchResult
from torrents.interfaces import DownloadResult, TorrentProviderProtocol


def get_url(path: str = "") -> str:
    return f"https://{RUTRACKER_URL}{path}"


async def _authenticate(credentials: dict[str, str]) -> dict[str, str]:
    username = credentials.get("username")
    password = credentials.get("password")
    async with httpx.AsyncClient() as client:
        url = get_url("/forum/login.php")
        data = {
            "login_username": username,
            "login_password": password,
            "login": "%E2%F5%EE%E4",
        }
        response = await client.post(url, data=data)
        if response.status_code != 302:
            raise RutrackerApiError("Failed to authenticate")
    return {"bb_session": response.cookies.get("bb_session")}


class RutrackerTorrentProvider(TorrentProviderProtocol):
    name = "rutracker"
    max_query_length = None  # No query length limit for Rutracker
    requires_authentication = True

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    @property
    def base_url(self) -> str:
        """Return the base URL of the Rutracker tracker."""
        return get_url()

    def get_torrent_url(self, movie_id: int | str) -> str:
        """Get the full URL to the torrent page on Rutracker."""
        return f"{self.base_url}/viewtopic.php?t={movie_id}"

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        """Search for torrents on Rutracker.
        
        TODO: Implement HTML parsing for Rutracker search results.
        Currently returns empty list as placeholder.
        """
        # TODO: Implement Rutracker search HTML parsing
        return []

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        """Get detailed information about a torrent from Rutracker.
        
        TODO: Implement HTML parsing for Rutracker torrent details page.
        """
        raise NotImplementedError(
            "Rutracker torrent detail parsing is not yet implemented. "
            "HTML parsing needs to be added."
        )

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        """Download torrent file from Rutracker.
        
        TODO: Implement torrent file download from Rutracker.
        """
        raise NotImplementedError(
            "Rutracker torrent download is not yet implemented. "
            "Download functionality needs to be added."
        )
