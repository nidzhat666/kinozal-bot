import aiohttp
from bs4 import BeautifulSoup

from utilities.kinozal_utils import get_url


class MovieSearchService:
    def __init__(self, auth_cookies):
        self.auth_cookies = auth_cookies
        print(self.auth_cookies)

    async def search(self, query: str) -> str:
        url = get_url("/browse.php")
        params = {"s": query,
                  "v": 3001,  # 1080p
                  "t": 1  # Sort by queries
                  }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params,
                                   cookies=self.auth_cookies) as response:
                return await self.parse_format_search_results(await response.text())

    @staticmethod
    async def parse_format_search_results(results) -> str:
        soup = BeautifulSoup(results, features="html.parser")
        results_list = soup.find_all("td", class_="nam")
        for el in results_list:
            el.find("a")
        return ""
