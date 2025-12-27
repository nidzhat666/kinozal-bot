import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum

from aioqbt.api import AddFormBuilder
from aioqbt.client import APIClient

from utilities.format_utils import sanitize_fs_name

logger = logging.getLogger(__name__)


class TorrentStructure(Enum):
    """Torrent file structure type."""
    SINGLE_FILE = "single_file"
    FOLDER_ROOT = "folder_root"
    MIXED_ROOT = "mixed_root"


@dataclass
class TorrentRenameInfo:
    """Information needed to rename a torrent."""
    structure: TorrentStructure
    old_name: str
    new_name: str


async def add_torrent_and_rename(
    torrent_file_path: str,
    client: APIClient,
    category: str,
    original_title: str | None = None,
    year: int | str | None = None,
) -> None:
    """Add torrent to qBittorrent and rename based on TMDB metadata."""
    logger.info(f"Adding torrent: {torrent_file_path}")
    
    async with client:
        before_hashes = await _get_torrent_hashes(client)
        
        await _add_torrent(client, torrent_file_path, category)
        
        if not original_title:
            logger.info("No original title provided. Rename skipped.")
            return
            
        if before_hashes is None:
            return

        new_hash = await _wait_for_new_hash(client, before_hashes)
        if not new_hash:
            logger.error("Torrent added but new hash not found (timeout). Rename skipped.")
            return

        await _rename_torrent(client, new_hash, original_title, year)


async def _get_torrent_hashes(client: APIClient) -> set[str] | None:
    """Get current torrent hashes or None if failed."""
    try:
        torrents = await client.torrents.info()
        return {t.hash for t in torrents}
    except Exception as e:
        logger.warning(f"Failed to fetch torrent list: {e}. Rename will be skipped.")
        return None


async def _add_torrent(client: APIClient, file_path: str, category: str) -> None:
    """Add torrent file to qBittorrent."""
    form = AddFormBuilder.with_client(client)
    form = form.category(category).auto_tmm(True)
    
    with open(file_path, "rb") as f:
        form = form.include_file(f.read(), filename=file_path)
    
    await client.torrents.add(form=form.build())
    logger.info("Torrent added to download queue.")


async def _wait_for_new_hash(
    client: APIClient,
    before_hashes: set[str],
    timeout: float = 10.0,
    poll_interval: float = 0.5,
) -> str | None:
    """Poll for new torrent hash that wasn't in before_hashes."""
    start_time = asyncio.get_running_loop().time()
    
    while asyncio.get_running_loop().time() - start_time < timeout:
        try:
            current_torrents = await client.torrents.info()
            current_hashes = {t.hash for t in current_torrents}
            new_hashes = current_hashes - before_hashes
            
            if new_hashes:
                if len(new_hashes) > 1:
                    logger.warning(f"Multiple new torrents detected: {new_hashes}")
                return next(iter(new_hashes))
        except Exception as e:
            logger.warning(f"Error polling torrents: {e}")
        
        await asyncio.sleep(poll_interval)
    
    return None


async def _rename_torrent(
    client: APIClient,
    torrent_hash: str,
    title: str,
    year: int | str | None,
) -> None:
    """Rename torrent files/folder based on title and year."""
    new_name = sanitize_fs_name(f"{title} ({year})" if year else title)
    logger.info(f"Attempting to rename torrent {torrent_hash} to '{new_name}'")
    
    try:
        files = await client.torrents.files(torrent_hash)
    except Exception as e:
        logger.error(f"Failed to get files for hash {torrent_hash}: {e}")
        return

    if not files:
        logger.warning(f"No files found for torrent {torrent_hash}")
        return

    rename_info = _analyze_torrent_structure(files, new_name)
    
    if rename_info.old_name == rename_info.new_name:
        logger.info("Name already matches target. No rename needed.")
        return
    
    try:
        await _apply_rename(client, torrent_hash, rename_info)
    except Exception as e:
        logger.error(f"Failed to rename torrent: {e}")


def _analyze_torrent_structure(files: list, new_name: str) -> TorrentRenameInfo:
    """Analyze torrent file structure and determine rename strategy."""
    if len(files) == 1 and "/" not in files[0].name:
        _, ext = os.path.splitext(files[0].name)
        return TorrentRenameInfo(
            structure=TorrentStructure.SINGLE_FILE,
            old_name=files[0].name,
            new_name=f"{new_name}{ext}",
        )
    
    roots = {f.name.split("/", 1)[0] for f in files}
    
    if len(roots) == 1:
        return TorrentRenameInfo(
            structure=TorrentStructure.FOLDER_ROOT,
            old_name=next(iter(roots)),
            new_name=new_name,
        )
    
    logger.info(f"Mixed-root torrent with {len(roots)} roots. Rename skipped.")
    return TorrentRenameInfo(
        structure=TorrentStructure.MIXED_ROOT,
        old_name="",
        new_name="",
    )


async def _apply_rename(
    client: APIClient,
    torrent_hash: str,
    info: TorrentRenameInfo,
) -> None:
    """Apply the rename operation based on structure type."""
    if info.structure == TorrentStructure.SINGLE_FILE:
        logger.info(f"Renaming single file: '{info.old_name}' -> '{info.new_name}'")
        await client.torrents.rename_file(torrent_hash, info.old_name, info.new_name)
    elif info.structure == TorrentStructure.FOLDER_ROOT:
        logger.info(f"Renaming root folder: '{info.old_name}' -> '{info.new_name}'")
        await client.torrents.rename_folder(torrent_hash, info.old_name, info.new_name)

