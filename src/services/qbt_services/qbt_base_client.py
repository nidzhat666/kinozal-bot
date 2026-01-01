from time import perf_counter

from aioqbt.client import create_client, APIClient

from utilities.qbt_utils import get_url
from utilities.logger_utils import get_service_logger

logger = get_service_logger("qbt")


async def get_client(username: str, password: str) -> APIClient:
    started_at = perf_counter()
    url = get_url("/api/v2/")
    client = await create_client(url, username, password)
    duration_ms = int((perf_counter() - started_at) * 1000)
    logger.info(
        "Connected to qBittorrent",
        url=url,
        duration_ms=duration_ms,
    )
    return client
