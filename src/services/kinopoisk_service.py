from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.config import (
    KINOPOISK_API_KEY,
    KINOPOISK_API_URL,
    KINOPOISK_SEARCH_LIMIT,
)
from custom_types.kinopoisk_types import (
    KinopoiskMovieBase,
    KinopoiskMovieDetails,
    KinopoiskSearchResponse,
    KinopoiskSeason,
    KinopoiskSeasonListResponse,
)
from services.exceptions import KinopoiskApiError

logger = logging.getLogger(__name__)


class KinopoiskApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_limit: int = 10,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_limit = default_limit
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        page: int = 1,
    ) -> KinopoiskSearchResponse:
        trimmed_query = query.strip()
        if not trimmed_query:
            return KinopoiskSearchResponse()

        params = {
            "query": trimmed_query,
            "page": page,
            "limit": limit or self._default_limit,
        }

        payload = await self._request("GET", "/movie/search", params=params)
        try:
            return KinopoiskSearchResponse.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            message = "Failed to parse Kinopoisk search response."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise KinopoiskApiError(message) from exc

    async def get_movie_details(self, movie_id: int | str) -> KinopoiskMovieDetails:
        payload = await self._request("GET", f"/movie/{movie_id}")
        try:
            return KinopoiskMovieDetails.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            message = f"Failed to parse Kinopoisk movie details for id {movie_id}."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise KinopoiskApiError(message) from exc

    async def get_seasons(
        self,
        movie_id: int | str,
        *,
        limit: int | None = None,
        page: int = 1,
    ) -> list[KinopoiskSeason]:
        params: dict[str, Any] = {
            "movieId": movie_id,
            "page": page,
            "limit": limit or 100,
            "selectFields": ["number", "airDate", "episodesCount", "name", "enName"],
            "notNullFields": ["number", "airDate"],
        }

        payload = await self._request("GET", "/season", params=params)
        try:
            response = KinopoiskSeasonListResponse.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
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
        headers = {
            "Accept": "application/json",
            "X-API-KEY": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                )
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

        try:
            return response.json()
        except ValueError as exc:
            message = f"Kinopoisk response from {response.request.url} is not valid JSON."
            logger.error(message)
            raise KinopoiskApiError(message) from exc


kinopoisk_client = KinopoiskApiClient(
    base_url=KINOPOISK_API_URL,
    api_key=KINOPOISK_API_KEY,
    default_limit=KINOPOISK_SEARCH_LIMIT,
)


__all__ = [
    "KinopoiskApiClient",
    "KinopoiskMovieBase",
    "KinopoiskMovieDetails",
    "KinopoiskSearchResponse",
    "KinopoiskSeason",
    "KinopoiskSeasonListResponse",
    "kinopoisk_client",
]

