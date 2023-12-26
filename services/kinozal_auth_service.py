import aiohttp

from bot.logger_config import setup_logging
from config import KINOZAL_URL
from utilities import kinozal_utils

logger = setup_logging(__name__)


class KinozalAuthService:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    async def authenticate(self) -> aiohttp.ClientSession:
        url = kinozal_utils.get_url("/takelogin.php")
        data = {
            "username": self.username,
            "password": self.password
        }

        session = aiohttp.ClientSession()
        try:
            response = await session.post(url, data=data)
            if response.status != 200:
                await session.close()
                raise Exception(f"Kinozal Status code: {response.status}")
            return session

        except Exception as e:
            await session.close()
            logger.error(f"Failed to authenticate with Kinozal: {e}")
            raise e
