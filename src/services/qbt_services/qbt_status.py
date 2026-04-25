import asyncio
import logging

from aioqbt.api import TorrentInfo
from aioqbt.client import APIClient

logger = logging.getLogger(__name__)


async def torrents_info(
    client: APIClient,
    filter_: str | None = None,
    sort: str | None = None,
    reverse: bool = False,
    hashes: list | tuple = (),
) -> list[TorrentInfo]:
    """
    Get torrents info
    :param client: qBittorrent API client
    :param filter_: Filter torrents by state
    :param sort: Sort torrents by field
    :param reverse: Reverse sort order
    :param hashes: Filter by torrent hashes
    :return: list[TorrentInfo]
    """
    torrents = []
    async with client:
        for torrent in await client.torrents.info(
            filter=filter_, sort=sort, reverse=reverse, hashes=hashes
        ):
            torrents.append(torrent)
    return torrents


if __name__ == "__main__":
    from bot.config import QBT_CREDENTIALS
    from services.qbt_services import get_client

    async def main():
        async with await get_client(**QBT_CREDENTIALS) as qbt_client:
            torrents = await torrents_info(qbt_client, sort="added_on")
            for torrent in torrents:
                print(
                    torrent.name,
                    torrent.state,
                    torrent.added_on,
                    torrent.hash,
                    torrent.progress,
                    torrent.eta,
                )

    asyncio.run(main())
