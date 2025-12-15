import logging

from aioqbt.api import TorrentInfo
from aioqbt.client import APIClient

from services.qbt_services.qbt_status import torrents_info

logger = logging.getLogger(__name__)


async def get_torrent_details(client: APIClient, torrent_hash: str) -> TorrentInfo:
    """Retrieves the details for a single torrent."""
    async with client:
        torrent = next(
            iter(
                await torrents_info(
                    client, filter_=torrent_hash, hashes=(torrent_hash,)
                )
            ),
            None,
        )
        return torrent
