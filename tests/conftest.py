"""Shared test fixtures.

Every PDF the suite touches is generated here, at test time. None are committed.
That is partly hygiene — this is a privacy tool and a stray real document in the
git history would be a bad look — and partly practical: generated pages carry a
known marker, so after a split or a reorder we can extract the text and assert
that page 3 really is the page that started as page 3. Eyeballing a PDF proves
nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pikepdf
import pypdfium2
import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

PageMaker = Callable[..., Path]


def marker(page_number: int) -> str:
    """The text stamped on a generated page, and the thing we assert on later."""
    return f"ModPDF test page {page_number}"


def build_pdf(path: Path, page_count: int, *, title: str | None = None) -> Path:
    """Write a PDF whose every page announces which page it started as."""
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    if title:
        pdf.setTitle(title)
    for number in range(1, page_count + 1):
        pdf.setFont("Helvetica", 36)
        pdf.drawString(72, 500, marker(number))
        pdf.showPage()
    pdf.save()
    return path


def page_text(path: Path) -> list[str]:
    """Extract the text of each page, so page identity can be asserted."""
    document = pypdfium2.PdfDocument(path)
    try:
        return [page.get_textpage().get_text_range().strip() for page in document]
    finally:
        document.close()


def page_markers(path: Path) -> list[int]:
    """Which original page numbers a document now contains, in order.

    This is the assertion most operation tests want: ``page_markers(out) == [3, 1, 2]``
    says precisely what a reorder was supposed to do.
    """
    numbers = []
    for text in page_text(path):
        prefix = "ModPDF test page "
        if prefix not in text:
            raise AssertionError(f"page is not a generated test page: {text!r}")
        numbers.append(int(text.split(prefix, 1)[1].split()[0]))
    return numbers


def build_bookmarked_pdf(path: Path, page_count: int) -> Path:
    """A generated PDF with a two-level outline, for testing bookmark survival.

    Every third page starting at page 1 gets a top-level "Chapter" entry; the
    pages between get "Section" entries nested underneath it.
    """
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    for number in range(1, page_count + 1):
        pdf.setFont("Helvetica", 36)
        pdf.drawString(72, 500, marker(number))
        pdf.bookmarkPage(f"page{number}")
        if number % 3 == 1:
            pdf.addOutlineEntry(f"Chapter {number // 3 + 1}", f"page{number}", level=0)
        else:
            pdf.addOutlineEntry(f"Section {number}", f"page{number}", level=1)
        pdf.showPage()
    pdf.save()
    return path


def outline_summary(path: Path) -> list[tuple[int, str, int]]:
    """Flatten a document's outline to (depth, title, 1-based page) triples."""
    summary: list[tuple[int, str, int]] = []
    with pikepdf.open(path) as pdf:
        with pdf.open_outline() as outline:

            def walk(items: list[pikepdf.OutlineItem], depth: int) -> None:
                for item in items:
                    destination: Any = item.destination
                    page = pdf.pages.index(destination[0]) + 1
                    summary.append((depth, str(item.title), page))
                    walk(item.children, depth + 1)

            walk(outline.root, 0)
    return summary


@pytest.fixture
def make_pdf(tmp_path: Path) -> PageMaker:
    """Factory fixture: ``make_pdf(5)`` gives a five-page document in tmp_path."""
    counter = 0

    def factory(page_count: int = 3, *, name: str | None = None, title: str | None = None) -> Path:
        nonlocal counter
        counter += 1
        filename = name or f"doc{counter}.pdf"
        return build_pdf(tmp_path / filename, page_count, title=title)

    return factory
