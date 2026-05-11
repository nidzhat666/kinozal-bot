"""Tests for ``_build_provider_queries`` from torrent_search_utils."""

from __future__ import annotations

import pytest

from models.search_provider_types import MediaDetails, Provider
from utilities.torrent_search_utils import _build_provider_queries


class _StaticProvider:
    """Minimal provider double exposing the bits the helper touches."""

    def __init__(self, name: str, queries: list[str] | None, raises: bool = False) -> None:
        self.name = name
        self._queries = queries or []
        self._raises = raises
        self.build_queries_called_with: dict | None = None

    def build_queries(self, **kwargs) -> list[str]:
        self.build_queries_called_with = kwargs
        if self._raises:
            raise RuntimeError("boom")
        return list(self._queries)


def _media(title: str = "Title") -> MediaDetails:
    return MediaDetails(
        provider_id="1",
        provider=Provider.TMDB,
        title=title,
        original_title=None,
        year=2024,
        is_series=False,
    )


class TestBuildProviderQueries:
    def test_uses_provider_queries_and_skips_fallback_when_media_details_given(self):
        """Given media_details and provider queries, when building,
        then only provider queries are returned (no fallback contamination)."""
        provider = _StaticProvider("kinozal", ["q1", "q2"])

        queries = _build_provider_queries(
            provider,
            fallback_query="USER_TYPED",
            media_details=_media(),
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["q1", "q2"]
        assert "USER_TYPED" not in queries

    def test_falls_back_when_no_media_details(self):
        """Given no media_details, when building, then fallback_query is used."""
        provider = _StaticProvider("kinozal", [])

        queries = _build_provider_queries(
            provider,
            fallback_query="USER_TYPED",
            media_details=None,
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["USER_TYPED"]

    def test_falls_back_when_provider_build_queries_raises(self):
        """Given a broken provider, when building, then fallback keeps the search alive."""
        provider = _StaticProvider("rutracker", None, raises=True)

        queries = _build_provider_queries(
            provider,
            fallback_query="USER_TYPED",
            media_details=_media(),
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["USER_TYPED"]

    def test_falls_back_when_provider_returns_empty(self):
        """Given a provider that produces no queries, when building, then fallback is used."""
        provider = _StaticProvider("rutracker", [])

        queries = _build_provider_queries(
            provider,
            fallback_query="USER_TYPED",
            media_details=_media(),
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["USER_TYPED"]

    def test_deduplicates_and_strips(self):
        """Given duplicate / whitespace-only entries, when building, then they are dropped."""
        provider = _StaticProvider("kinozal", ["q1", "  q1  ", "  ", "q2"])

        queries = _build_provider_queries(
            provider,
            fallback_query="",
            media_details=_media(),
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["q1", "q2"]

    @pytest.mark.parametrize(("season_number", "season_year"), [(2, 2024), (None, None)])
    def test_passes_kwargs_to_provider(self, season_number, season_year):
        """Given season parameters, when building, then they are forwarded verbatim."""
        provider = _StaticProvider("kinozal", ["q"])
        media = _media()

        _build_provider_queries(
            provider,
            fallback_query="",
            media_details=media,
            season_number=season_number,
            season_year=season_year,
            season_pack_only=True,
        )

        assert provider.build_queries_called_with == {
            "media_details": media,
            "season_number": season_number,
            "season_year": season_year,
            "season_pack_only": True,
        }
