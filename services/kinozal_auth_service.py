import aiohttp
import logging
from bot.config import KINOZAL_URL
from utilities import kinozal_utils

logger = logging.getLogger(__name__)


class KinozalAuthService:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    async def authenticate(self) -> dict:
        url = kinozal_utils.get_url("/takelogin.php")
        data = {
            "username": self.username,
            "password": self.password
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as response:
                if response.status != 200:
                    logger.error("Authentication failed")
                    raise Exception("Authentication failed")
                uid = session.cookie_jar._cookies[(KINOZAL_URL, "/")]["uid"]
                pass_ = session.cookie_jar._cookies[(KINOZAL_URL, "/")]["pass"]
                return {"uid": uid.value, "pass": pass_.value}
