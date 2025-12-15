import logging

from aioqbt.client import APIClient
from aioqbt.api import AddFormBuilder

logger = logging.getLogger(__name__)


async def add_torrent(torrent_file_path: str, client: APIClient, category: str):
    """
    Add torrents to download queue
    :param category:
    :param torrent_file_path:
    :param client:
    :return: None
    """
    logger.info(f"Adding torrents to download queue: {torrent_file_path}")
    async with client:
        form = AddFormBuilder.with_client(client)
        form = form.category(category)
        form = form.auto_tmm(True)
        with open(torrent_file_path, "rb") as f:
            logging.debug(f"Reading torrent file: {torrent_file_path}")
            torrent_content = f.read()
            form = form.include_file(torrent_content, filename=torrent_file_path)
        await client.torrents.add(form=form.build())
        logger.info("Torrent added to download queue.")
