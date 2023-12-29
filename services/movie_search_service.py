import asyncio
import logging
from typing import List

import aiohttp
from bs4 import BeautifulSoup

from utilities.kinozal_utils import get_url

logger = logging.getLogger(__name__)


class MovieSearchService:
    def __init__(self, auth_cookies):
        self.auth_cookies = auth_cookies
        print(self.auth_cookies)

    async def search(self, query: str) -> list[dict]:
        url = get_url("/browse.php")
        params = {"s": query,
                  "v": 3001,  # 1080p
                  "t": 1  # Sort by seeds
                  }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params,
                                   cookies=self.auth_cookies) as response:
                return self.parse_search_results(await response.text())

    @staticmethod
    def parse_search_results(text) -> list[dict]:
        soup = BeautifulSoup(text, features="html.parser")
        results_list: list[BeautifulSoup] = soup.find_all("tr", class_="bg")
        result = []
        for el in results_list:
            name: BeautifulSoup = el.find("td", class_="nam")
            if name is None:
                continue
            size = el.find_all("td", class_="s")[1]
            id_ = name.find("a").get("href").split("=")[-1]
            result.append(dict(name=name.find("a").text,
                               size=size.text,
                               id=id_))
        logger.info(f"Found results: {result}")
        return result
