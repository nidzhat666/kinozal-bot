import asyncio
from typing import List

import aiohttp
from bs4 import BeautifulSoup

from utilities.kinozal_utils import get_url


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
        results_list = soup.find_all("td", class_="nam")
        result = []
        for el in results_list:
            result.append(dict(name=el.find("a").text))
        return result
