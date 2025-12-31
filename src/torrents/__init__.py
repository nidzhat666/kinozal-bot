from __future__ import annotations

from bot.config import (
    KINOZAL_CREDENTIALS,
    RUTRACKER_CREDENTIALS,
    USE_KINOZAL,
    USE_RUTRACKER,
)

from torrents.provider_registry import registry
from torrents.providers import KinozalTorrentProvider
from torrents.interfaces import TorrentProviderProtocol
from torrents.providers.rutracker import RutrackerTorrentProvider

# Register providers based on configuration flags
if USE_KINOZAL:
    registry.register(KinozalTorrentProvider(credentials=KINOZAL_CREDENTIALS))

if USE_RUTRACKER:
    registry.register(
        RutrackerTorrentProvider(credentials=RUTRACKER_CREDENTIALS)
    )


def get_torrent_provider(name: str | None = None) -> TorrentProviderProtocol:
    """Get torrent provider by name.
    
    If name is None, returns the first available provider.
    Raises KeyError if provider with given name is not found.
    Raises LookupError if no providers are registered.
    """
    if name:
        return registry.get(name)
    
    # Return first available provider if no name specified
    provider_names = list(registry.names())
    if not provider_names:
        raise LookupError("No torrent providers are registered.")
    return registry.get(provider_names[0])


def get_registered_providers() -> tuple[str, ...]:
    return tuple(registry.names())


def get_active_providers() -> list[TorrentProviderProtocol]:
    """Get list of all active (registered) torrent providers."""
    return [registry.get(name) for name in registry.names()]


__all__ = [
    "get_torrent_provider",
    "get_registered_providers",
    "get_active_providers",
]
