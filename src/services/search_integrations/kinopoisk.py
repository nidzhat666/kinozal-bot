from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.config import KINOPOISK_API_KEY, KINOPOISK_API_URL, KINOPOISK_SEARCH_LIMIT
from models.kinopoisk_types import (
    KinopoiskMovieBase,
    KinopoiskMovieDetails,
    KinopoiskSearchResponse,
    KinopoiskSeason,
    KinopoiskSeasonListResponse,
)
from models.search_provider_types import (
    MediaDetails,
    MediaItem,
    Provider,
    SearchResults,
    SeasonDetails,
)
from services.exceptions import KinopoiskApiError
from services.search_integrations.interface import SearchProvider

logger = logging.getLogger(__name__)


class KinopoiskService(SearchProvider):
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        default_limit: int = 10,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_limit = default_limit

    async def search(self, query: str) -> SearchResults:
        trimmed_query = query.strip()
        if not trimmed_query:
            return SearchResults()

        params = {
            "query": trimmed_query,
            "limit": self._default_limit,
            "page": 1,
        }

        payload = await self._request("GET", "/movie/search", params=params)
        try:
            response = KinopoiskSearchResponse.model_validate(payload)
        except Exception as exc:
            message = "Failed to parse Kinopoisk search response."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise KinopoiskApiError(message) from exc

        return self._to_search_results(response)

    async def get_details(self, media_id: str) -> MediaDetails:
        payload = await self._request("GET", f"/movie/{media_id}")
        try:
            details = KinopoiskMovieDetails.model_validate(payload)
        except Exception as exc:
            message = f"Failed to parse Kinopoisk movie details for id {media_id}."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise KinopoiskApiError(message) from exc

        seasons = await self._get_seasons(media_id)
        return self._to_media_details(details, seasons)

    async def _get_seasons(self, movie_id: str) -> list[KinopoiskSeason]:
        params: dict[str, Any] = {
            "movieId": movie_id,
            "page": 1,
            "limit": 50,  # Assuming a series won't have more than 50 seasons
        }

        payload = await self._request("GET", "/season", params=params)
        try:
            response = KinopoiskSeasonListResponse.model_validate(payload)
        except Exception as exc:
            message = f"Failed to parse Kinopoisk seasons for movie id {movie_id}."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise KinopoiskApiError(message) from exc
        return response.docs

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise KinopoiskApiError("Kinopoisk API key is not configured.")

        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json", "X-API-KEY": self._api_key}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            message = f"Kinopoisk request to {url} failed: {exc}"
            logger.error(message)
            raise KinopoiskApiError(message) from exc

        if response.status_code >= 400:
            message = (
                f"Kinopoisk request to {response.request.url} failed with status "
                f"{response.status_code}: {response.text}"
            )
            logger.error(message)
            raise KinopoiskApiError(message)

        return response.json()

    def _to_search_results(self, response: KinopoiskSearchResponse) -> SearchResults:
        items = [self._movie_base_to_media_item(movie) for movie in response.docs]
        return SearchResults(results=items)

    def _movie_base_to_media_item(self, movie: KinopoiskMovieBase) -> MediaItem:
        return MediaItem(
            provider_id=str(movie.id),
            provider=Provider.KINOPOISK,
            title=movie.name or "Без названия",
            original_title=movie.alternative_name or movie.en_name,
            year=movie.year,
            poster_url=movie.poster.preview_url if movie.poster else None,
            is_series=movie.is_series,
        )

    def _to_media_details(self, details: KinopoiskMovieDetails, seasons: list[KinopoiskSeason]) -> MediaDetails:
        base = self._movie_base_to_media_item(details)
        season_details = [
            SeasonDetails(
                season_number=s.number,
                year=s.air_date.year if s.air_date else None,
                episodes_count=s.episodes_count,
            )
            for s in seasons
            if s.number is not None
        ]
        return MediaDetails(
            **base.model_dump(),
            description=details.description or details.short_description,
            seasons=season_details,
        )


kinopoisk_service = KinopoiskService(
    api_key=KINOPOISK_API_KEY,
    base_url=KINOPOISK_API_URL,
    default_limit=KINOPOISK_SEARCH_LIMIT,
)

__all__ = ["KinopoiskService", "kinopoisk_service"]
