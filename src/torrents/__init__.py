from __future__ import annotations

from bot.config import KINOZAL_CREDENTIALS, RUTRACKER_CREDENTIALS

from torrents.provider_registry import registry
from torrents.providers import KinozalTorrentProvider
from torrents.interfaces import TorrentProviderProtocol
from torrents.providers.rutracker import RutrackerTorrentProvider

registry.register(
    KinozalTorrentProvider(credentials=KINOZAL_CREDENTIALS), default=True
)
registry.register(RutrackerTorrentProvider(credentials=RUTRACKER_CREDENTIALS))


def get_torrent_provider(name: str | None = None) -> TorrentProviderProtocol:
    if name:
        return registry.get(name)
    return registry.get_default()


def get_registered_providers() -> tuple[str, ...]:
    return tuple(registry.names())


__all__ = [
    "get_torrent_provider",
    "get_registered_providers",
]
