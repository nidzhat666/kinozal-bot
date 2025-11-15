from __future__ import annotations

from abc import ABC, abstractmethod

from models.search_provider_types import MediaDetails, SearchResults


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str) -> SearchResults:
        ...

    @abstractmethod
    async def get_details(self, media_id: str) -> MediaDetails:
        ...


__all__ = ["SearchProvider"]
