from __future__ import annotations

from bot.config import SEARCH_PROVIDER
from custom_types.search_provider_types import Provider
from services.search_integrations.interface import SearchProvider
from services.search_integrations.kinopoisk import kinopoisk_service
from services.search_integrations.tmdb import tmdb_service


def get_search_provider() -> SearchProvider:
    if SEARCH_PROVIDER == Provider.TMDB:
        return tmdb_service
    if SEARCH_PROVIDER == Provider.KINOPOISK:
        return kinopoisk_service
    raise ValueError(f"Unknown search provider: {SEARCH_PROVIDER}")


__all__ = ["get_search_provider"]
