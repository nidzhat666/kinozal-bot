import logging
from asyncio import gather

import httpx

from bot.config import PLEX_TOKEN, PLEX_URL

logger = logging.getLogger(__name__)


def get_url(path: str):
    return PLEX_URL + path + "?X-Plex-Token=" + PLEX_TOKEN


def get_headers():
    return {
        "Accept": "text/plain, */*; q=0.01",
        "Accept-Language": "en",
        "Connection": "keep-alive",
    }


async def call_plex(library_id: int) -> bool:
    headers = get_headers()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            get_url(f"/library/sections/{library_id}/refresh"), headers=headers
        )
        if response.status_code == 200:
            logger.info(f"Plex library refresh initiated successfully with id: {library_id}")
            return True
        logger.error(f"Failed to initiate Plex library refresh with id: {library_id}")
        return False


async def refresh_plex_library():
    results = await gather(*(call_plex(library_id) for library_id in range(1, 5)))
    return (
        "Plex libraries refreshed successfully."
        if any(results)
        else "Failed to refresh Plex libraries."
    )
