import logging
import tempfile
import aiofile
from aiohttp import ClientSession

from services.exceptions import KinozalApiError
from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieDownloadService:
    def __init__(self, movie_id, auth_cookies: dict):
        self.auth_cookies = auth_cookies
        self.movie_id = movie_id
        self.url = get_url(f"/download.php?id={self.movie_id}")

    @property
    def filename(self):
        return f"{self.movie_id}.torrent"

    @property
    def file_path(self):
        path = tempfile.gettempdir()
        return f"{path}/{self.filename}"

    async def download_movie(self) -> dict[str, str]:
        async with ClientSession(cookies=self.auth_cookies) as session:
            async with session.get(self.url) as response:
                if response.status != 200:
                    raise KinozalApiError(f"Failed to download movie "
                                          f"with status code: {response.status}")
                response_file = await response.read()
                if "pay.php" in str(response_file):
                    raise KinozalApiError("You are not allowed to download this torrent.")
                async with aiofile.async_open(self.file_path, "wb") as f:
                    await f.write(response_file)
        return {"file_path": self.file_path,
                "filename": f"{self.movie_id}.torrent"}

