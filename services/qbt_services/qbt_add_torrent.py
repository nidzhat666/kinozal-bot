import logging

from aioqbt.client import APIClient
from aioqbt.api import AddFormBuilder

from bot.constants import TORRENT_DEFAULT_CATEGORY

logger = logging.getLogger(__name__)


async def add_torrent(torrent_file_info: dict, client: APIClient):
    """
    Add torrents to download queue
    :param torrent_file_info:
    :param client:
    :return: None
    """
    logger.info(f"Adding torrents to download queue: {torrent_file_info}")
    async with client:
        form = AddFormBuilder.with_client(client)
        form.category = TORRENT_DEFAULT_CATEGORY
        form.auto_tmm = True
        if torrent_file_path := torrent_file_info["file_path"]:
            with open(torrent_file_path, 'rb') as f:
                logging.debug(f"Reading torrent file: {torrent_file_path}")
                torrent_content = f.read()
                form = form.include_file(torrent_content, filename=torrent_file_info["filename"])
        else:
            logger.error(f"Torrent file path not found: {torrent_file_info}")
        await client.torrents.add(form=form.build())
        logger.info("Torrent added to download queue.")

