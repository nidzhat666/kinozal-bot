"""Tests for the ``_is_fuzzy_match`` title-matching heuristic."""

from __future__ import annotations

import pytest

from utilities.torrent_search_utils import _is_fuzzy_match


class TestKinozalStyleTitles:
    def test_full_title_in_parentheses_after_short_alias(self):
        """Given Kinozal's ``Short (Full) ... / English /`` layout,
        when matching against the full Russian title, then it matches."""
        result = "Питт (Больница Питт) (2 сезон: 1-15 серии из 15) / The Pitt / 2026 / WEB-DL"

        assert _is_fuzzy_match(result, ["Больница Питт"])

    def test_english_title_after_first_slash(self):
        """Given English original title living after a ``/``, when matching, then it matches."""
        result = "Питт (Больница Питт) (2 сезон: 1-15 серии из 15) / The Pitt / 2026 / WEB-DL"

        assert _is_fuzzy_match(result, ["The Pitt"])


class TestPrefixMatches:
    def test_classic_russian_prefix(self):
        result = "Друзья / Friends / 1994 / WEB-DL"

        assert _is_fuzzy_match(result, ["Друзья"])

    def test_season_prefix_is_stripped(self):
        result = "S02 Что-то там"

        assert _is_fuzzy_match(result, ["Что-то там"])


class TestFalsePositives:
    def test_single_word_substring_does_not_match(self):
        """Given the long-standing rule, when expected is a single word,
        then it must not match as a mid-string substring."""
        result = "Smiling Friends / 2022"

        assert not _is_fuzzy_match(result, ["Friends"])

    def test_unrelated_title_does_not_match(self):
        result = "Какое-то кино / Some Movie / 2020"

        assert not _is_fuzzy_match(result, ["The Pitt"])


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("Питт (Больница Питт) / The Pitt / 2026", "Больница Питт"),
        ("Some show / The Pitt season 2", "The Pitt"),
        ("Title - Sub - Главное название - Эпизод", "Главное название"),
    ],
)
def test_multi_word_phrase_matches_anywhere(result, expected):
    """Multi-word expected titles match as whole-word phrases anywhere in the result."""
    assert _is_fuzzy_match(result, [expected])
