import logging

from aioqbt.client import APIClient
from aioqbt.api import AddFormBuilder

logger = logging.getLogger(__name__)


async def add_torrent(torrent_file_info: dict, client: APIClient, category: str):
    """
    Add torrents to download queue
    :param category:
    :param torrent_file_info:
    :param client:
    :return: None
    """
    logger.info(f"Adding torrents to download queue: {torrent_file_info}")
    async with client:
        form = AddFormBuilder.with_client(client)
        form = form.category(category)
        form = form.auto_tmm(True)
        if torrent_file_path := torrent_file_info["file_path"]:
            with open(torrent_file_path, 'rb') as f:
                logging.debug(f"Reading torrent file: {torrent_file_path}")
                torrent_content = f.read()
                form = form.include_file(torrent_content, filename=torrent_file_info["filename"])
        else:
            logger.error(f"Torrent file path not found: {torrent_file_info}")
        await client.torrents.add(form=form.build())
        logger.info("Torrent added to download queue.")
