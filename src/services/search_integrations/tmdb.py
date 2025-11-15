from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.config import TMDB_API_TOKEN, TMDB_API_URL
from custom_types.search_provider_types import (
    MediaDetails,
    MediaItem,
    Provider,
    SearchResults,
    SeasonDetails,
)
from custom_types.tmdb_types import (
    TmdbMovieDetails,
    TmdbMovieSearchResult,
    TmdbSearchResponse,
    TmdbTVShowDetails,
    TmdbTVShowSearchResult,
)
from services.exceptions import TmdbApiError
from services.search_integrations.interface import SearchProvider

logger = logging.getLogger(__name__)


class TmdbService(SearchProvider):
    def __init__(self, api_token: str | None, base_url: str) -> None:
        self._api_token = api_token
        self._base_url = base_url.rstrip("/")
        self._image_base_url = "https://image.tmdb.org/t/p/w500"

    async def search(self, query: str) -> SearchResults:
        if not query.strip():
            return SearchResults()

        params = {"query": query, "language": "ru-RU"}
        payload = await self._request("GET", "/search/multi", params=params)
        try:
            response = TmdbSearchResponse.model_validate(payload)
        except Exception as exc:
            message = "Failed to parse TMDB search response."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise TmdbApiError(message) from exc

        return self._to_search_results(response)

    async def get_details(self, media_id: str) -> MediaDetails:
        media_type, tmdb_id = self._parse_media_id(media_id)

        if media_type == "movie":
            path = f"/movie/{tmdb_id}"
            parser = TmdbMovieDetails
        elif media_type == "tv":
            path = f"/tv/{tmdb_id}"
            parser = TmdbTVShowDetails
        else:
            raise TmdbApiError(f"Unsupported media type: {media_type}")

        params = {"language": "ru-RU"}
        payload = await self._request("GET", path, params=params)
        try:
            details = parser.model_validate(payload)
        except Exception as exc:
            message = f"Failed to parse TMDB details for {media_id}."
            logger.error("%s Raw payload: %s", message, payload, exc_info=True)
            raise TmdbApiError(message) from exc

        return self._to_media_details(details)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_token:
            raise TmdbApiError("TMDB API token is not configured.")

        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_token}",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            message = f"TMDB request to {url} failed: {exc}"
            logger.error(message)
            raise TmdbApiError(message) from exc

        if response.status_code >= 400:
            message = f"TMDB request to {response.request.url} failed with status {response.status_code}: {response.text}"
            logger.error(message)
            raise TmdbApiError(message)

        return response.json()

    def _to_search_results(self, response: TmdbSearchResponse) -> SearchResults:
        items = []
        for result in response.results:
            if isinstance(result, TmdbMovieSearchResult):
                item = self._movie_search_result_to_media_item(result)
            elif isinstance(result, TmdbTVShowSearchResult):
                item = self._tv_show_search_result_to_media_item(result)
            else:
                continue
            items.append(item)
        return SearchResults(results=items)

    def _movie_search_result_to_media_item(self, movie: TmdbMovieSearchResult) -> MediaItem:
        return MediaItem(
            provider_id=f"movie:{movie.id}",
            provider=Provider.TMDB,
            title=movie.title or "Без названия",
            original_title=movie.original_title,
            year=movie.release_date.year if movie.release_date else None,
            poster_url=f"{self._image_base_url}{movie.poster_path}" if movie.poster_path else None,
            is_series=False,
        )

    def _tv_show_search_result_to_media_item(self, tv_show: TmdbTVShowSearchResult) -> MediaItem:
        return MediaItem(
            provider_id=f"tv:{tv_show.id}",
            provider=Provider.TMDB,
            title=tv_show.name or "Без названия",
            original_title=tv_show.original_name,
            year=tv_show.first_air_date.year if tv_show.first_air_date else None,
            poster_url=f"{self._image_base_url}{tv_show.poster_path}" if tv_show.poster_path else None,
            is_series=True,
        )

    def _to_media_details(self, details: TmdbMovieDetails | TmdbTVShowDetails) -> MediaDetails:
        if isinstance(details, TmdbMovieDetails):
            return self._movie_details_to_media_details(details)
        if isinstance(details, TmdbTVShowDetails):
            return self._tv_show_details_to_media_details(details)
        raise TypeError(f"Unsupported details type: {type(details)}")

    def _movie_details_to_media_details(self, details: TmdbMovieDetails) -> MediaDetails:
        base = self._movie_search_result_to_media_item(details)
        return MediaDetails(
            **base.model_dump(),
            description=details.overview,
            seasons=[],
        )

    def _tv_show_details_to_media_details(self, details: TmdbTVShowDetails) -> MediaDetails:
        base = self._tv_show_search_result_to_media_item(details)
        seasons = [
            SeasonDetails(
                season_number=s.season_number,
                year=s.air_date.year if s.air_date else None,
                episodes_count=s.episode_count,
            )
            for s in details.seasons
            if s.season_number > 0
        ]
        return MediaDetails(
            **base.model_dump(),
            description=details.overview,
            seasons=seasons,
        )

    @staticmethod
    def _parse_media_id(media_id: str) -> tuple[str, int]:
        try:
            media_type, tmdb_id_str = media_id.split(":")
            return media_type, int(tmdb_id_str)
        except (ValueError, IndexError) as exc:
            raise TmdbApiError(f"Invalid TMDB media ID format: {media_id}") from exc


tmdb_service = TmdbService(api_token=TMDB_API_TOKEN, base_url=TMDB_API_URL)

__all__ = ["TmdbService", "tmdb_service"]
