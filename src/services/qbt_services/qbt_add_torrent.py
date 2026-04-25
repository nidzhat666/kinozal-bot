from time import perf_counter

from aioqbt.api import AddFormBuilder
from aioqbt.client import APIClient

from utilities.logger_utils import get_service_logger

logger = get_service_logger("qbt")


async def add_torrent(torrent_file_path: str, client: APIClient, category: str):
    """Add torrents to download queue."""
    started_at = perf_counter()
    bound_logger = logger.bind(operation="add_torrent")
    bound_logger.info(
        "Adding torrent to download queue",
        torrent_file_path=torrent_file_path,
        category=category,
    )
    async with client:
        form = AddFormBuilder.with_client(client)
        form = form.category(category)
        form = form.auto_tmm(True)
        with open(torrent_file_path, "rb") as f:
            torrent_content = f.read()
            form = form.include_file(torrent_content, filename=torrent_file_path)
        await client.torrents.add(form=form.build())
        duration_ms = int((perf_counter() - started_at) * 1000)
        bound_logger.info(
            "Torrent added to download queue",
            duration_ms=duration_ms,
        )
