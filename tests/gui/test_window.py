"""Tests for the window itself, on the offscreen platform.

These check the wiring rather than the pixels: that opening a file populates
the grid, that edits reach the session, and — the one that matters most — that
the window reaches the filesystem only through `modpdf.tasks`, so it cannot
sidestep the security layer by coming in through a window.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QScrollArea

from modpdf.gui.session import load
from modpdf.gui.widgets import ElidedLabel
from modpdf.gui.window import PAGE_ROLE, MainWindow
from modpdf.security import netguard
from tests.conftest import PageMaker, build_hostile_pdf, page_markers

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def window() -> Iterator[MainWindow]:
    """A window per test, closed afterwards so its render thread is joined."""
    made = MainWindow()
    yield made
    made.close()


def open_now(window: MainWindow, path: Path) -> None:
    """Load synchronously, skipping the worker thread, then hand it to the window."""
    window._loaded(load(path))


class TestOpening:
    def test_starts_with_no_document(self, window: MainWindow) -> None:
        assert window.session is None
        assert window.stack.currentIndex() == 0

    def test_opening_shows_the_pages(self, window: MainWindow, make_pdf: PageMaker) -> None:
        open_now(window, make_pdf(7))
        assert window.session is not None
        assert window.grid.count() == 7
        assert window.stack.currentIndex() == 1

    def test_each_tile_remembers_its_source_page(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        open_now(window, make_pdf(4))
        pages = [window.grid.item(row).data(PAGE_ROLE) for row in range(4)]
        assert pages == [0, 1, 2, 3]

    def test_the_header_reports_the_document(self, window: MainWindow, make_pdf: PageMaker) -> None:
        open_now(window, make_pdf(5, name="contract.pdf"))
        assert window.title_label.text() == "contract.pdf"
        assert "5 pages" in window.subtitle_label.text()


class TestTheSafetyChip:
    def test_a_clean_document_says_so(self, window: MainWindow, tmp_path: Path) -> None:
        from tests.conftest import build_pdf

        # A generated PDF still carries reportlab's author metadata.
        open_now(window, build_pdf(tmp_path / "plain.pdf", 3))
        assert window.safety_chip.isVisibleTo(window)

    def test_a_hostile_document_raises_concerns(self, window: MainWindow, tmp_path: Path) -> None:
        open_now(window, build_hostile_pdf(tmp_path / "hostile.pdf"))
        assert window.session is not None
        labels = {c.label for c in window.session.inspection.concerns}
        assert "JavaScript" in labels
        assert window.review_button.isVisibleTo(window)

    def test_findings_are_explained_not_just_listed(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        open_now(window, build_hostile_pdf(tmp_path / "hostile.pdf"))
        html = window.findings_label.text()
        assert "JavaScript" in html
        assert "most common way a PDF is used" in html


class TestEditing:
    def test_deleting_selected_pages(self, window: MainWindow, make_pdf: PageMaker) -> None:
        open_now(window, make_pdf(6))
        window.grid.item(0).setSelected(True)
        window.grid.item(1).setSelected(True)
        window.delete_selected()

        assert window.session is not None
        assert window.session.order == [2, 3, 4, 5]
        assert window.grid.count() == 4

    def test_duplicating_a_page(self, window: MainWindow, make_pdf: PageMaker) -> None:
        open_now(window, make_pdf(3))
        window.grid.item(1).setSelected(True)
        window.duplicate_selected()
        assert window.session is not None
        assert window.session.order == [0, 1, 1, 2]

    def test_revert_restores_the_file(self, window: MainWindow, make_pdf: PageMaker) -> None:
        open_now(window, make_pdf(4))
        window.grid.item(0).setSelected(True)
        window.delete_selected()
        window.revert()
        assert window.session is not None
        assert window.session.modified is False
        assert window.grid.count() == 4

    def test_editing_never_touches_the_file(self, window: MainWindow, make_pdf: PageMaker) -> None:
        source = make_pdf(5)
        before = source.read_bytes()
        open_now(window, source)
        window.grid.item(0).setSelected(True)
        window.delete_selected()
        window.duplicate_selected()
        assert source.read_bytes() == before


class TestSaving:
    def test_saving_writes_the_edited_order(
        self, window: MainWindow, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        open_now(window, make_pdf(5))
        window.grid.item(0).setSelected(True)
        window.delete_selected()

        assert window.session is not None
        out = window.session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [2, 3, 4, 5]


class TestTheGuardIsOn:
    def test_the_window_works_with_the_network_blocked(
        self, window: MainWindow, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        """The GUI gets the same guarantee as the command line."""
        source = make_pdf(4)
        with netguard.denied():
            open_now(window, source)
            window.grid.item(0).setSelected(True)
            window.delete_selected()
            assert window.session is not None
            out = window.session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [2, 3, 4]


class TestLongFileNames:
    """A long file name has no spaces to wrap at. It used to widen the whole
    inspector past its edge, cutting off every value and button on the
    right, because each panel's scroll area sized its content to the widest
    label instead of to the panel. Seen first on a real 40-page document."""

    NAME = "Ley-Orgánica-de-Telecomunicaciones-Registro-Oficial-Suplemento.pdf"

    @pytest.fixture
    def shown(self, window: MainWindow, make_pdf: PageMaker) -> MainWindow:
        window.resize(1118, 860)  # the size of the window the bug was reported at
        window.show()
        open_now(window, make_pdf(3, name=self.NAME))
        QCoreApplication.processEvents()
        return window

    def test_no_panel_is_wider_than_the_inspector(self, shown: MainWindow) -> None:
        for key in shown.panel_index:
            shown._show_panel(key)
            QCoreApplication.processEvents()
            area = shown.panels.currentWidget()
            assert isinstance(area, QScrollArea)
            content = area.widget()
            assert content is not None
            assert content.width() <= area.viewport().width(), key

    def test_the_name_is_shortened_in_the_middle_with_the_full_name_on_hover(
        self, shown: MainWindow
    ) -> None:
        label = shown.doc_fact_values["name"]
        assert isinstance(label, ElidedLabel)
        assert "…" in label.displayedText()
        assert label.displayedText().startswith("Ley-")
        assert label.displayedText().endswith(".pdf")  # the extension stays visible
        assert label.toolTip() == self.NAME
        assert label.text() == self.NAME  # code reading the label still gets it all

    def test_a_short_name_is_shown_whole_with_no_tooltip(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window.resize(1118, 860)
        window.show()
        open_now(window, make_pdf(3, name="short.pdf"))
        QCoreApplication.processEvents()
        label = window.doc_fact_values["name"]
        assert isinstance(label, ElidedLabel)
        assert label.displayedText() == "short.pdf"
        assert label.toolTip() == ""

    def test_a_small_file_size_is_not_shown_as_zero_megabytes(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        open_now(window, make_pdf(1))
        assert "0.0 MB" not in window.subtitle_label.text()
        assert "KB" in window.subtitle_label.text()
