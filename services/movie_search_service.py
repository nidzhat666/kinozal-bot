import aiohttp
from services.kinozal_auth_service import KinozalAuthService


class MovieSearchService:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def search(self, query: str):
        pass
        # async with self.session.get()

    async def format_search_results(self, results):
        formatted_results = ""
        return formatted_results
