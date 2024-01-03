import asyncio
import logging

from aioqbt.api import TorrentInfo, InfoFilter
from aioqbt.client import APIClient

logger = logging.getLogger(__name__)


async def torrents_info(client: APIClient,
                        filter_: str = None,
                        sort: str = None) -> list[TorrentInfo]:
    """
    Get torrents info
    :param sort:
    :param filter_:
    :param client:
    :return: list[dict]
    """
    logger.info("Getting torrents info.")
    torrents = []
    async with client:
        for torrent in await client.torrents.info(filter=filter_,
                                                  sort=sort):
            torrents.append(torrent)
    logger.info("Got torrents info.")
    return torrents


if __name__ == '__main__':
    from services.qbt_services import get_client
    from bot.config import QBT_CREDENTIALS


    async def main():
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            torrents = await torrents_info(qbt_client,
                                           sort="added_on")
            for torrent in torrents:
                print(torrent.name, torrent.state, torrent.added_on, torrent.hash, torrent.progress, torrent.eta)


    asyncio.run(main())
