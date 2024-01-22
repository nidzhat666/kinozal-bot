import logging

from aioqbt.client import APIClient

logger = logging.getLogger(__name__)


async def pause_torrent(client: APIClient, torrent_hash: str) -> None:
    """Pauses the torrent with the given hash."""
    async with client:
        await client.torrents.pause(hashes=[torrent_hash])


async def resume_torrent(client: APIClient, torrent_hash: str) -> None:
    """Resumes the torrent with the given hash."""
    async with client:
        await client.torrents.resume(hashes=[torrent_hash])


async def delete_torrent(client: APIClient, torrent_hash: str) -> None:
    """Resumes the torrent with the given hash."""
    async with client:
        await client.torrents.delete(hashes=[torrent_hash], delete_files=True)
