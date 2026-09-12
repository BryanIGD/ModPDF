"""Tests for page spec parsing.

This module is deliberately thorough. Page specs are the one place where a
silent off-by-one turns into handing someone the wrong page of a confidential
document, so the cost of over-testing here is much lower than the cost of a gap.
"""

from __future__ import annotations

import pytest

from modpdf.pagespec import PageSpecError, parse_pagespec


def pages(spec: str, count: int) -> list[int]:
    """Parse, then convert back to 1-based numbers so the assertions read naturally."""
    return [i + 1 for i in parse_pagespec(spec, count)]


class TestSinglePages:
    def test_first_page(self) -> None:
        assert pages("1", 10) == [1]

    def test_last_page_by_number(self) -> None:
        assert pages("10", 10) == [10]

    def test_negative_one_is_the_last_page(self) -> None:
        assert pages("-1", 10) == [10]

    def test_negative_counts_back_from_the_end(self) -> None:
        assert pages("-3", 10) == [8]

    def test_single_page_document(self) -> None:
        assert pages("1", 1) == [1]
        assert pages("-1", 1) == [1]


class TestRanges:
    def test_inclusive_at_both_ends(self) -> None:
        assert pages("2-4", 10) == [2, 3, 4]

    def test_whole_document(self) -> None:
        assert pages("1-10", 10) == list(range(1, 11))

    def test_open_ended_runs_to_the_last_page(self) -> None:
        assert pages("8-", 10) == [8, 9, 10]

    def test_range_of_one_page(self) -> None:
        assert pages("5-5", 10) == [5]

    def test_negative_end(self) -> None:
        assert pages("3--1", 5) == [3, 4, 5]


class TestCombinations:
    def test_comma_separated(self) -> None:
        assert pages("1-3,7,9-", 10) == [1, 2, 3, 7, 9, 10]

    def test_whitespace_is_forgiven(self) -> None:
        assert pages("  1-3 , 7 ", 10) == [1, 2, 3, 7]

    def test_first_and_last(self) -> None:
        assert pages("1,-1", 10) == [1, 10]


class TestOrderAndDuplicatesAreMeaningful:
    """Both carry intent: 3,1,2 reorders and 1,1 repeats. Neither is normalised."""

    def test_order_is_preserved(self) -> None:
        assert pages("3,1,2", 5) == [3, 1, 2]

    def test_duplicates_are_kept(self) -> None:
        assert pages("1,1,2", 5) == [1, 1, 2]

    def test_overlapping_ranges_are_not_merged(self) -> None:
        assert pages("1-3,2-4", 10) == [1, 2, 3, 2, 3, 4]


class TestRejections:
    @pytest.mark.parametrize(
        ("spec", "count", "expected_in_message"),
        [
            ("0", 5, "numbered from 1"),
            ("0-3", 5, "numbered from 1"),
            ("99", 10, "document has 10 pages"),
            ("1-99", 10, "document has 10 pages"),
            ("-9", 5, "document has 5 pages"),
            ("5-1", 10, "runs backwards"),
            ("", 5, "empty page spec"),
            ("   ", 5, "empty page spec"),
            ("1,,2", 5, "stray comma"),
            ("1,", 5, "stray comma"),
            ("abc", 5, "could not understand"),
            ("1-2-3", 5, "could not understand"),
            ("1.5", 5, "could not understand"),
        ],
    )
    def test_rejected_with_a_useful_message(
        self, spec: str, count: int, expected_in_message: str
    ) -> None:
        with pytest.raises(PageSpecError, match=expected_in_message):
            parse_pagespec(spec, count)

    def test_backwards_range_suggests_the_fix(self) -> None:
        with pytest.raises(PageSpecError, match="meant 1-5"):
            parse_pagespec("5-1", 10)

    def test_empty_document(self) -> None:
        with pytest.raises(PageSpecError, match="no pages"):
            parse_pagespec("1", 0)
