"""Tests for bookmark survival across page operations.

Bookmarks are the failure that users notice last and resent most: a split
report still opens, still has the right pages, and has quietly lost the only
practical way to navigate it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pikepdf
import pytest

from modpdf.document import save_pdf
from modpdf.ops.merge import merge_documents
from modpdf.ops.outline import page_mapping
from modpdf.ops.select import select_pages
from tests.conftest import build_bookmarked_pdf, build_pdf, outline_summary


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return build_bookmarked_pdf(tmp_path / "book.pdf", 8)


class TestPageMapping:
    def test_maps_each_page_to_its_new_home(self) -> None:
        assert page_mapping([2, 0, 1]) == {2: 0, 0: 1, 1: 2}

    def test_a_duplicated_page_maps_to_its_first_copy(self) -> None:
        """Otherwise every bookmark on that page would appear twice."""
        assert page_mapping([0, 0, 1]) == {0: 0, 1: 2}

    def test_dropped_pages_are_absent(self) -> None:
        assert page_mapping([5]) == {5: 0}


class TestSelectKeepsBookmarks:
    def test_a_slice_keeps_only_what_still_exists(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "slice.pdf"
        with pikepdf.open(book) as pdf:
            save_pdf(select_pages(pdf, [3, 4, 5]), out)

        assert outline_summary(out) == [
            (0, "Chapter 2", 1),
            (1, "Section 5", 2),
            (1, "Section 6", 3),
        ]

    def test_reversing_pages_remaps_every_entry(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "reversed.pdf"
        with pikepdf.open(book) as pdf:
            save_pdf(select_pages(pdf, list(reversed(range(8)))), out)

        summary = outline_summary(out)
        assert (0, "Chapter 1", 8) in summary
        assert (1, "Section 8", 1) in summary
        assert len(summary) == 8, "no entry should be lost when every page survives"

    def test_orphaned_children_are_promoted_not_discarded(self, book: Path, tmp_path: Path) -> None:
        """Dropping a chapter heading must not take the whole chapter with it."""
        out = tmp_path / "orphans.pdf"
        with pikepdf.open(book) as pdf:
            save_pdf(select_pages(pdf, [1, 2]), out)  # keep pages 2-3, drop the heading

        assert outline_summary(out) == [
            (0, "Section 2", 1),
            (0, "Section 3", 2),
        ]

    def test_hierarchy_is_preserved(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "all.pdf"
        with pikepdf.open(book) as pdf:
            save_pdf(select_pages(pdf, list(range(8))), out)

        assert outline_summary(out) == outline_summary(book)

    def test_document_without_bookmarks_is_fine(self, tmp_path: Path) -> None:
        plain = build_pdf(tmp_path / "plain.pdf", 4)
        out = tmp_path / "out.pdf"
        with pikepdf.open(plain) as pdf:
            save_pdf(select_pages(pdf, [1, 0]), out)
        assert outline_summary(out) == []


class TestMergeKeepsBookmarks:
    def test_second_document_entries_are_shifted(self, tmp_path: Path) -> None:
        first = build_bookmarked_pdf(tmp_path / "a.pdf", 4)
        second = build_bookmarked_pdf(tmp_path / "b.pdf", 3)
        out = tmp_path / "merged.pdf"

        with pikepdf.open(first) as a, pikepdf.open(second) as b:
            save_pdf(merge_documents([a, b]), out)

        summary = outline_summary(out)
        pages = [page for _, _, page in summary]
        assert pages == sorted(pages), "merged bookmarks should run front to back"
        assert max(pages) == 7
        assert len(summary) == 7

    def test_merging_a_plain_document_keeps_the_other_bookmarks(self, tmp_path: Path) -> None:
        plain = build_pdf(tmp_path / "plain.pdf", 3)
        book = build_bookmarked_pdf(tmp_path / "book.pdf", 3)
        out = tmp_path / "merged.pdf"

        with pikepdf.open(plain) as a, pikepdf.open(book) as b:
            save_pdf(merge_documents([a, b]), out)

        assert [page for _, _, page in outline_summary(out)] == [4, 5, 6]


class TestNamedDestinations:
    """LaTeX and InDesign output points bookmarks at names, not pages directly."""

    @staticmethod
    def _build(path: Path, *, use_name_tree: bool) -> Path:
        pdf = pikepdf.Pdf.new()
        for _ in range(4):
            pdf.add_blank_page()

        if use_name_tree:
            pairs: list[Any] = []
            for index in range(4):
                pairs.append(pikepdf.String(f"sec{index}"))
                pairs.append(pikepdf.Array([pdf.pages[index].obj, pikepdf.Name("/Fit")]))
            pdf.Root["/Names"] = pdf.make_indirect(
                pikepdf.Dictionary(
                    Dests=pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(pairs)))
                )
            )
            destinations: list[Any] = [pikepdf.String(f"sec{i}") for i in range(4)]
        else:
            legacy = pikepdf.Dictionary()
            for index in range(4):
                legacy[f"/sec{index}"] = pikepdf.Array([pdf.pages[index].obj, pikepdf.Name("/Fit")])
            pdf.Root["/Dests"] = pdf.make_indirect(legacy)
            destinations = [pikepdf.Name(f"/sec{i}") for i in range(4)]

        with pdf.open_outline() as outline:
            for index, destination in enumerate(destinations):
                outline.root.append(pikepdf.OutlineItem(f"Named {index + 1}", destination))

        pdf.save(path)
        return path

    @pytest.mark.parametrize("use_name_tree", [False, True], ids=["legacy-dests", "name-tree"])
    def test_named_destinations_are_resolved(self, tmp_path: Path, use_name_tree: bool) -> None:
        source = self._build(tmp_path / "named.pdf", use_name_tree=use_name_tree)
        out = tmp_path / "out.pdf"

        with pikepdf.open(source) as pdf:
            save_pdf(select_pages(pdf, [3, 1]), out)

        assert outline_summary(out) == [
            (0, "Named 2", 2),
            (0, "Named 4", 1),
        ]
