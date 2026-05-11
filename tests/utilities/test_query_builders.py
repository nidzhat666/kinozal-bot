"""Tests for the per-provider query builders."""

from __future__ import annotations

import pytest

from models.search_provider_types import MediaDetails, Provider, SeasonDetails
from utilities.query_builders import build_expressive_queries, build_flat_queries


def _make_media_details(
    *,
    title: str,
    original_title: str | None,
    year: int | None,
    is_series: bool,
    seasons: list[SeasonDetails] | None = None,
) -> MediaDetails:
    return MediaDetails(
        provider_id="1",
        provider=Provider.TMDB,
        title=title,
        original_title=original_title,
        year=year,
        is_series=is_series,
        seasons=seasons or [],
    )


class TestBuildExpressiveQueries:
    def test_series_season_emits_alternation_and_year_range(self):
        """Given a series + season + year, when building expressive queries,
        then we get title-only, title+season, and combined alternation forms."""
        media = _make_media_details(
            title="Больница Питт",
            original_title="The Pitt",
            year=2025,
            is_series=True,
            seasons=[SeasonDetails(season_number=2, year=2026)],
        )

        queries = build_expressive_queries(
            media,
            season_number=2,
            season_year=2026,
            season_pack_only=False,
        )

        assert "Больница Питт (сезон 2|season 2|S02)" in queries
        assert "The Pitt (сезон 2|season 2|S02)" in queries
        assert "Больница Питт (сезон 2|season 2|S02) (2025 | 2026 | 2027)" in queries
        assert "The Pitt (сезон 2|season 2|S02) (2025 | 2026 | 2027)" in queries
        assert any(q.startswith("(") and "2026" in q for q in queries)

    def test_series_season_pack_only_uses_year_only_form(self):
        """Given season_pack_only=True, when building, then no per-season suffix."""
        media = _make_media_details(
            title="Больница Питт",
            original_title="The Pitt",
            year=2025,
            is_series=True,
        )

        queries = build_expressive_queries(
            media,
            season_number=None,
            season_year=None,
            season_pack_only=True,
        )

        assert all("сезон" not in q.lower() for q in queries)
        assert any("Больница Питт" in q for q in queries)
        assert any("The Pitt" in q for q in queries)

    def test_movie_without_year_falls_back_to_titles(self):
        """Given a movie with no year, when building, then plain titles are returned."""
        media = _make_media_details(
            title="Кино",
            original_title="Movie",
            year=None,
            is_series=False,
        )

        queries = build_expressive_queries(
            media,
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["Кино", "Movie"]

    def test_drops_queries_exceeding_max_length(self):
        """Given a strict max_length, when building, then long queries are filtered."""
        media = _make_media_details(
            title="A" * 100,
            original_title=None,
            year=2024,
            is_series=False,
        )

        queries = build_expressive_queries(
            media,
            season_number=None,
            season_year=None,
            season_pack_only=False,
            max_length=64,
        )

        assert all(len(q) <= 64 for q in queries)


class TestBuildFlatQueries:
    def test_series_season_emits_flat_token_queries(self):
        """Given series + season, when building flat queries, then no parens/pipes."""
        media = _make_media_details(
            title="Больница Питт",
            original_title="The Pitt",
            year=2025,
            is_series=True,
            seasons=[SeasonDetails(season_number=2, year=2026)],
        )

        queries = build_flat_queries(
            media,
            season_number=2,
            season_year=2026,
            season_pack_only=False,
        )

        assert all("(" not in q and "|" not in q for q in queries)
        assert "Больница Питт сезон 2" in queries
        assert "Больница Питт season 2" in queries
        assert "Больница Питт S02" in queries
        assert "The Pitt сезон 2" in queries
        assert "The Pitt season 2" in queries
        assert "The Pitt S02" in queries
        assert "Больница Питт S02 2026" in queries
        assert "The Pitt S02 2026" in queries

    def test_movie_with_year(self):
        """Given a movie with a year, when building flat queries,
        then we get ``<title> <year>`` per title."""
        media = _make_media_details(
            title="Кино",
            original_title="Movie",
            year=2024,
            is_series=False,
        )

        queries = build_flat_queries(
            media,
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["Кино 2024", "Movie 2024"]

    def test_deduplicates_repeated_titles(self):
        """Given identical title and original_title, when building, then no duplicates."""
        media = _make_media_details(
            title="Solo",
            original_title="Solo",
            year=2024,
            is_series=False,
        )

        queries = build_flat_queries(
            media,
            season_number=None,
            season_year=None,
            season_pack_only=False,
        )

        assert queries == ["Solo 2024"]


@pytest.mark.parametrize("builder", [build_expressive_queries, build_flat_queries])
def test_empty_titles_return_empty(builder):
    """Given a media item with empty titles, when building, then no queries."""
    media = _make_media_details(
        title="",
        original_title=None,
        year=2024,
        is_series=False,
    )

    queries = builder(
        media,
        season_number=None,
        season_year=None,
        season_pack_only=False,
    )

    assert queries == []
