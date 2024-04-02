from multiprocessing import AuthenticationError

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
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status != 200:
                        error_message = f"Authentication failed with status code: {response.status}"
                        logger.error(error_message)
                        raise AuthenticationError(error_message)
                    uid = session.cookie_jar._cookies[(KINOZAL_URL, "/")].get("uid")
                    pass_ = session.cookie_jar._cookies[(KINOZAL_URL, "/")].get("pass")
                    return {"uid": uid.value, "pass": pass_.value}
        except aiohttp.ClientError as e:
            error_message = f"HTTP client error during authentication: {e}"
            logger.error(error_message)
            raise AuthenticationError(error_message)
        except Exception as e:
            error_message = f"Unexpected error during authentication: {e}"
            logger.error(error_message)
            raise AuthenticationError(error_message)
