from __future__ import annotations

from collections.abc import Iterable

from torrents.interfaces import TorrentProviderProtocol


class TorrentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TorrentProviderProtocol] = {}

    def register(
        self, provider: TorrentProviderProtocol
    ) -> None:
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        if name in self._providers:
            del self._providers[name]

    def get(self, name: str) -> TorrentProviderProtocol:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Torrent provider '{name}' is not registered.") from exc

    def names(self) -> Iterable[str]:
        return self._providers.keys()


registry = TorrentProviderRegistry()
