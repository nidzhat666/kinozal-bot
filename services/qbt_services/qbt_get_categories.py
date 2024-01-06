import logging

from aioqbt.client import APIClient

logger = logging.getLogger(__name__)


async def qbt_get_categories(client: APIClient) -> list:
    """
    Get categories from qBittorrent
    :param client:
    :return: list[dict]
    """
    logger.info("Getting categories from qBittorrent.")
    async with client:
        logger.info("Got categories from qBittorrent.")
        categories = await client.torrents.categories()
        return list(categories.keys())
