import asyncio
import logging
from typing import List

import aiohttp
from bs4 import BeautifulSoup

from services.exceptions import SearchError
from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieSearchService:
    def __init__(self, auth_cookies):
        self.auth_cookies = auth_cookies

    async def search(self, query: str) -> list[dict]:
        url = get_url("/browse.php")
        params = {"s": query, "v": 3001, "t": 1}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, cookies=self.auth_cookies) as response:
                    if response.status != 200:
                        error_message = f"Search request failed with status code: {response.status}"
                        logger.error(error_message)
                        raise SearchError(error_message)
                    return self.parse_search_results(await response.text())
        except aiohttp.ClientError as e:
            error_message = f"HTTP client error during search: {e}"
            logger.error(error_message)
            raise SearchError(error_message)
        except Exception as e:
            error_message = f"Unexpected error during search: {e}"
            logger.error(error_message)
            raise SearchError(error_message)

    @staticmethod
    def parse_search_results(text) -> list[dict]:
        try:
            soup = BeautifulSoup(text, features="html.parser")
            results_list = soup.find_all("tr", class_="bg")
            result = []
            for el in results_list:
                name = el.find("td", class_="nam")
                if name is None:
                    continue
                size = el.find_all("td", class_="s")[1]
                id_ = name.find("a").get("href").split("=")[-1]
                result.append(dict(name=name.find("a").text, size=size.text, id=id_))
            logger.info(f"Found results: {result}")
            return result
        except Exception as e:
            error_message = f"Error parsing search results: {e}"
            logger.error(error_message)
            raise SearchError(error_message)
