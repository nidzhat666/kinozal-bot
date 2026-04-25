from __future__ import annotations

from typing import TYPE_CHECKING

from bot.config import (
    KINOZAL_CREDENTIALS,
    RUTRACKER_CREDENTIALS,
    USE_KINOZAL,
    USE_RUTRACKER,
)
from torrents.provider_registry import registry

if TYPE_CHECKING:
    from torrents.interfaces import TorrentProviderProtocol
from torrents.providers import KinozalTorrentProvider
from torrents.providers.rutracker import RutrackerTorrentProvider

# Register providers based on configuration flags
if USE_KINOZAL:
    registry.register(KinozalTorrentProvider(credentials=KINOZAL_CREDENTIALS))

if USE_RUTRACKER:
    registry.register(RutrackerTorrentProvider(credentials=RUTRACKER_CREDENTIALS))


def get_torrent_provider(name: str) -> TorrentProviderProtocol:
    """Get torrent provider by name.

    Args:
        name: Provider name (required, no default).

    Returns:
        TorrentProviderProtocol instance.

    Raises:
        KeyError: If provider with given name is not found.
        ValueError: If name is not provided.
    """
    if not name:
        raise ValueError("Provider name is required. Cannot use default provider.")

    return registry.get(name)


def get_registered_providers() -> tuple[str, ...]:
    return tuple(registry.names())


def get_active_providers() -> list[TorrentProviderProtocol]:
    """Get list of all active (registered) torrent providers."""
    return [registry.get(name) for name in registry.names()]


__all__ = [
    "get_active_providers",
    "get_registered_providers",
    "get_torrent_provider",
]
