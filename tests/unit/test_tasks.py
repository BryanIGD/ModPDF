"""Tests for `modpdf.tasks` functions that have no dedicated CLI command.

Most of `tasks.py` is already exercised end-to-end through the CLI in
`tests/integration/test_commands.py`. `append_document` backs the desktop
app's Open button — specifically what it does when a document is already
open — and nothing on the command line, so it is tested directly here
instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modpdf import tasks
from modpdf.document import EncryptedDocumentError
from tests.conftest import PageMaker, page_markers


class TestAppendDocument:
    def test_the_addition_lands_after_the_base(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        first = make_pdf(3, name="first.pdf")
        second = make_pdf(2, name="second.pdf")
        out = tmp_path / "combined.pdf"

        written, added_pages = tasks.append_document(first, [0, 1, 2], second, out)

        assert written == out
        assert added_pages == 2
        assert page_markers(out) == [1, 2, 3, 1, 2]

    def test_pending_edits_on_the_base_are_kept(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        """The order passed in, not the file's own order, decides what "the
        base document" means — a page already deleted or moved must not
        reappear just because a second file was added."""
        first = make_pdf(3, name="first.pdf")
        second = make_pdf(1, name="second.pdf")
        out = tmp_path / "combined.pdf"

        # As if page 2 had been dragged to the front and page 3 deleted.
        _written, added_pages = tasks.append_document(first, [1, 0], second, out)

        assert added_pages == 1
        assert page_markers(out) == [2, 1, 1]

    def test_repeats_in_the_order_duplicate_pages(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        first = make_pdf(2, name="first.pdf")
        second = make_pdf(1, name="second.pdf")
        out = tmp_path / "combined.pdf"

        written, _ = tasks.append_document(first, [0, 0, 1], second, out)
        assert page_markers(written) == [1, 1, 2, 1]

    def test_a_wrong_password_on_the_addition_is_reported(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        import pikepdf

        first = make_pdf(1, name="first.pdf")
        second_path = tmp_path / "second.pdf"
        with pikepdf.open(make_pdf(1, name="plain.pdf")) as pdf:
            pdf.save(second_path, encryption=pikepdf.Encryption(owner="owner", user="secret"))

        with pytest.raises(EncryptedDocumentError):
            tasks.append_document(first, [0], second_path, tmp_path / "out.pdf")

    def test_the_right_password_on_the_addition_works(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        import pikepdf

        first = make_pdf(1, name="first.pdf")
        second_path = tmp_path / "second.pdf"
        with pikepdf.open(make_pdf(1, name="plain.pdf")) as pdf:
            pdf.save(second_path, encryption=pikepdf.Encryption(owner="owner", user="secret"))
        out = tmp_path / "combined.pdf"

        written, added_pages = tasks.append_document(
            first, [0], second_path, out, addition_password="secret"
        )
        assert added_pages == 1
        assert page_markers(written) == [1, 1]

    def test_needs_at_least_two_files_worth_of_content_but_each_can_be_one_page(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        first = make_pdf(1, name="first.pdf")
        second = make_pdf(1, name="second.pdf")
        out = tmp_path / "combined.pdf"
        written, added_pages = tasks.append_document(first, [0], second, out)
        assert added_pages == 1
        assert page_markers(written) == [1, 1]
