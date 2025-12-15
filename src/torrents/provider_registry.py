from __future__ import annotations

from collections.abc import Iterable

from torrents.interfaces import TorrentProviderProtocol


class TorrentProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TorrentProviderProtocol] = {}
        self._default_provider: str | None = None

    def register(
        self, provider: TorrentProviderProtocol, *, default: bool = False
    ) -> None:
        self._providers[provider.name] = provider
        if default or not self._default_provider:
            self._default_provider = provider.name

    def unregister(self, name: str) -> None:
        if name in self._providers:
            del self._providers[name]
            if self._default_provider == name:
                self._default_provider = next(iter(self._providers), None)

    def get(self, name: str) -> TorrentProviderProtocol:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Torrent provider '{name}' is not registered.") from exc

    def get_default(self) -> TorrentProviderProtocol:
        if not self._default_provider:
            raise LookupError("No default torrent provider configured.")
        return self.get(self._default_provider)

    def set_default(self, name: str) -> None:
        if name not in self._providers:
            raise KeyError(f"Cannot set default. Provider '{name}' is not registered.")
        self._default_provider = name

    def names(self) -> Iterable[str]:
        return self._providers.keys()


registry = TorrentProviderRegistry()
