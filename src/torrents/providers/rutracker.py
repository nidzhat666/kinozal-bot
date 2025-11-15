import httpx

from bot.config import RUTRACKER_URL
from services.exceptions import RutrackerApiError
from models.movie_detail_service_types import MovieDetails
from torrents.interfaces import DownloadResult, TorrentProviderProtocol
from models.movie_detail_service_types import MovieSearchResult

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

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    async def search(
        self,
        query: str,
        *,
        requested_item: str | None = None,
        requested_type: str | None = None,
    ) -> list[MovieSearchResult]:
        raise NotImplementedError

    async def get_movie_detail(self, movie_id: int | str) -> MovieDetails:
        raise NotImplementedError

    async def download_movie(self, movie_id: int | str) -> DownloadResult:
        raise NotImplementedError
