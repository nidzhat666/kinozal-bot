import asyncio

import httpx

from bot.config import RUTRACKER_CREDENTIALS, RUTRACKER_URL
from services.exceptions import RutrackerApiError
from torrents.interfaces import (
    TorrentAuthServiceProtocol,
    TorrentDetailServiceProtocol,
    TorrentDownloadServiceProtocol,
    TorrentProviderProtocol,
    TorrentSearchServiceProtocol,
)

def get_url(path: str = "") -> str:
    return f"https://{RUTRACKER_URL}{path}"

class AuthService(TorrentAuthServiceProtocol):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    async def authenticate(self) -> dict[str, str]:
        async with httpx.AsyncClient() as client:
            url = get_url("/forum/login.php")
            data = {"login_username": self.username,
                    "login_password": self.password,
                    "login": "%E2%F5%EE%E4"}
            response = await client.post(url, data=data)
            if response.status_code != 302:
                raise RutrackerApiError("Failed to authenticate")
        return {"bb_session": response.cookies.get("bb_session")}





class RutrackerTorrentProvider(TorrentProviderProtocol):
    name = "rutracker"

    def __init__(self, *, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {}

    def get_auth_service(self) -> TorrentAuthServiceProtocol | None:
        if not self._credentials:
            return None
        username = self._credentials.get("username")
        password = self._credentials.get("password")
        if not username or not password:
            return None
        return AuthService(username=username, password=password)

    def get_search_service(self) -> TorrentSearchServiceProtocol:
        ...

    def get_detail_service(self) -> TorrentDetailServiceProtocol:
        ...

    def get_download_service(
        self, movie_id: int | str, auth_data: dict[str, str] | None = None
    ) -> TorrentDownloadServiceProtocol:
        if auth_data is None:
            raise ValueError("Kinozal download service requires auth data.")
        ...


if __name__ == "__main__":
    provider = RutrackerTorrentProvider(credentials=RUTRACKER_CREDENTIALS)
    service = provider.get_auth_service()
    a = asyncio.run(service.authenticate())
    pass