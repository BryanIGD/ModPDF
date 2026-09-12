"""Tests for `sanitize`.

The assertion that matters most is about bytes, not structure. Unlinking a piece
of JavaScript leaves it fully recoverable in the file, so several of these tests
search the raw output for the payload rather than asking the PDF object model
whether it is still referenced.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from modpdf.document import save_pdf
from modpdf.ops.sanitize import SanitizeReport, sanitize
from tests.conftest import (
    build_bookmarked_pdf,
    build_hostile_pdf,
    build_pdf,
    outline_summary,
    page_markers,
    page_text,
)


def clean(
    source: Path,
    target: Path,
    *,
    keep_metadata: bool = False,
    strip_links: bool = False,
) -> tuple[Path, SanitizeReport]:
    """Sanitize a file on disk and hand back the output path and the report."""
    with pikepdf.open(source) as pdf:
        result, report = sanitize(pdf, keep_metadata=keep_metadata, strip_links=strip_links)
        save_pdf(result, target, overwrite=True)
    return target, report


@pytest.fixture
def hostile(tmp_path: Path) -> Path:
    return build_hostile_pdf(tmp_path / "hostile.pdf")


class TestThePayloadBytesAreGone:
    """Not merely dereferenced — absent from the file."""

    @pytest.mark.parametrize(
        ("label", "needle"),
        [
            ("javascript", b"app.alert"),
            ("launch target", b"calc.exe"),
            ("open action", b"/OpenAction"),
            ("launch action", b"/Launch"),
        ],
    )
    def test_removed_from_the_raw_file(
        self, hostile: Path, tmp_path: Path, label: str, needle: bytes
    ) -> None:
        assert needle in hostile.read_bytes(), f"fixture should contain {label}"
        out, _ = clean(hostile, tmp_path / "clean.pdf")
        assert needle not in out.read_bytes(), f"{label} survived sanitizing"

    def test_the_tracker_uri_goes_with_strip_links(self, hostile: Path, tmp_path: Path) -> None:
        out, _ = clean(hostile, tmp_path / "clean.pdf", strip_links=True)
        assert b"tracker.example.com" not in out.read_bytes()


class TestWhatIsKept:
    def test_pages_and_their_order_survive(self, hostile: Path, tmp_path: Path) -> None:
        out, _ = clean(hostile, tmp_path / "clean.pdf")
        assert page_markers(out) == [1, 2, 3]

    def test_text_survives(self, hostile: Path, tmp_path: Path) -> None:
        out, _ = clean(hostile, tmp_path / "clean.pdf")
        assert "ModPDF test page 1" in page_text(out)[0]

    def test_bookmarks_survive(self, tmp_path: Path) -> None:
        """Navigation is content, not machinery."""
        source = build_bookmarked_pdf(tmp_path / "book.pdf", 6)
        out, _ = clean(source, tmp_path / "clean.pdf")
        assert len(outline_summary(out)) == 6

    def test_plain_links_are_kept_by_default(self, hostile: Path, tmp_path: Path) -> None:
        """A citation in a report is content; the reader has to click it."""
        out, _ = clean(hostile, tmp_path / "clean.pdf")
        assert b"tracker.example.com" in out.read_bytes()


class TestMetadata:
    def test_stripped_by_default(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "doc.pdf", 3, title="Board Minutes")
        out, _ = clean(source, tmp_path / "clean.pdf")
        with pikepdf.open(out) as pdf:
            assert dict(pdf.docinfo) == {}

    def test_kept_on_request(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "doc.pdf", 3, title="Board Minutes")
        out, _ = clean(source, tmp_path / "clean.pdf", keep_metadata=True)
        with pikepdf.open(out) as pdf:
            assert pdf.docinfo.get("/Title") == "Board Minutes"

    def test_the_author_name_is_not_in_the_output_bytes(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "doc.pdf", 3, title="Board Minutes")
        out, _ = clean(source, tmp_path / "clean.pdf")
        assert b"Board Minutes" not in out.read_bytes()


class TestTheReport:
    def test_lists_what_was_removed(self, hostile: Path, tmp_path: Path) -> None:
        _, report = clean(hostile, tmp_path / "clean.pdf")
        assert report.javascript >= 1
        assert report.open_action is True
        assert report.xfa is True
        assert report.embedded_files == 1
        assert report.actions_removed.get("/Launch") == 1
        assert report.metadata_stripped is True

    def test_an_already_clean_document_reports_nothing(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "plain.pdf", 2)
        out, _ = clean(source, tmp_path / "once.pdf")
        _, report = clean(out, tmp_path / "twice.pdf")
        assert report.anything_removed is False

    def test_sanitizing_is_idempotent(self, hostile: Path, tmp_path: Path) -> None:
        once, _ = clean(hostile, tmp_path / "once.pdf")
        twice, report = clean(once, tmp_path / "twice.pdf")
        assert report.anything_removed is False
        assert page_markers(twice) == [1, 2, 3]

    def test_revisions_collapsed_is_reported(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "doc.pdf", 2)
        with pikepdf.open(source) as pdf:
            result, report = sanitize(pdf, revisions=4)
            save_pdf(result, tmp_path / "clean.pdf")
        assert report.revisions_collapsed == 3


class TestRefusals:
    def test_a_document_with_no_pages_is_refused(self) -> None:
        empty = pikepdf.Pdf.new()
        with pytest.raises(ValueError, match="no pages"):
            sanitize(empty)


class TestItIsNotRedaction:
    """Documented explicitly, because assuming otherwise is how documents leak."""

    def test_visible_text_is_still_extractable(self, tmp_path: Path) -> None:
        source = build_pdf(tmp_path / "doc.pdf", 2)
        out, _ = clean(source, tmp_path / "clean.pdf")
        assert "ModPDF test page 1" in page_text(out)[0], (
            "sanitize removes machinery, not information — if this ever starts "
            "passing by removing text, the command has changed meaning"
        )
