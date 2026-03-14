from __future__ import annotations

from services.search_integrations.interface import SearchProvider
from services.search_integrations.tmdb import tmdb_service


def get_search_provider() -> SearchProvider:
    return tmdb_service


__all__ = ["get_search_provider"]
