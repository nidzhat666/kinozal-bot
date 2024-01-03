import logging

from aioqbt.client import create_client

from utilities.qbt_utils import get_url

logger = logging.getLogger(__name__)


async def get_client(username: str, password: str):
    url = get_url("/api/v2/")
    client = await create_client(url, username, password)
    logger.info(f"Connected to qBittorrent: {url}")
    return client
