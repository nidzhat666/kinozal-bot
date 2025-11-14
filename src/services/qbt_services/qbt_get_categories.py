import json
import logging

from aioqbt.client import APIClient

from services.redis_services.client import redis_client

CACHE_KEY = "qbt:categories"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # one week

logger = logging.getLogger(__name__)


async def qbt_get_categories(client: APIClient) -> list:
    """
    Get categories from qBittorrent
    :param client:
    :return: list[dict]
    """
    cached_categories = redis_client.get(CACHE_KEY)
    if cached_categories:
        logger.info("Returning cached categories from Redis.")
        return json.loads(cached_categories)

    logger.info("Getting categories from qBittorrent.")
    async with client:
        logger.info("Got categories from qBittorrent.")
        categories = await client.torrents.categories()
        category_names = list(categories.keys())

    redis_client.set(CACHE_KEY, json.dumps(category_names), ex=CACHE_TTL_SECONDS)
    return category_names
