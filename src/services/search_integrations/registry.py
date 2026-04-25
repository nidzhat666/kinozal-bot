from __future__ import annotations

from typing import TYPE_CHECKING

from services.search_integrations.tmdb import tmdb_service

if TYPE_CHECKING:
    from services.search_integrations.interface import SearchProvider


def get_search_provider() -> SearchProvider:
    return tmdb_service


__all__ = ["get_search_provider"]
