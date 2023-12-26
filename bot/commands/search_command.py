import logging

from services.movie_search_service import MovieSearchService
from services.kinozal_auth_service import KinozalAuthService
from config import KINOZAL_CREDENTIALS

logger = logging.getLogger(__name__)


async def handle_search_command(chat_id: int, query: str):
    auth_service = KinozalAuthService(**KINOZAL_CREDENTIALS)
    auth_cookies = await auth_service.authenticate()
    search_service = MovieSearchService(auth_cookies)
    results = await search_service.search(query)
    return format_search_results(results)


def format_search_results(results):
    return '\n'.join(f"{movie['title']} ({movie['year']})" for movie in results)
