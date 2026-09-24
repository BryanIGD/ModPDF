"""Tests for rendering thumbnails off the window's own thread.

The renderer was moved to a worker thread and then called directly from the
window — and a direct call runs on the calling thread, whatever thread the
object was moved to. Every page rendered on the window's thread, so a large
document froze the window while it loaded. These tests pin down that rendering
really happens elsewhere, and that now it is asynchronous, a late result for a
document or a size that is no longer shown cannot land on the wrong tile.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, Qt
from PySide6.QtGui import QImage

from modpdf.gui.session import load
from modpdf.gui.thumbnails import ThumbnailRenderer
from modpdf.gui.window import MainWindow
from modpdf.pdfium_lock import PDFIUM_LOCK
from tests.conftest import PageMaker
from tests.gui.conftest import wait_until

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def window() -> Iterator[MainWindow]:
    made = MainWindow()
    yield made
    made.close()


class TestRenderingIsOffTheWindowThread:
    def test_loading_returns_before_any_thumbnail_is_rendered(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        """Results arrive as queued signals, so until the event loop runs,
        none can have landed. When rendering happened inline, all six were
        already here — having frozen the window to get them."""
        window._loaded(load(make_pdf(6)))
        assert window._thumbnails == {}

    def test_pages_render_on_another_thread(self, window: MainWindow, make_pdf: PageMaker) -> None:
        emitted_on: list[int] = []
        # A direct connection runs in the emitting thread: the renderer's own.
        window.renderer.rendered.connect(
            lambda *_: emitted_on.append(threading.get_ident()),
            Qt.ConnectionType.DirectConnection,
        )

        window._loaded(load(make_pdf(3)))
        wait_until(lambda: len(window._thumbnails) == 3)

        assert emitted_on
        assert threading.get_ident() not in emitted_on

    def test_every_page_gets_its_thumbnail(self, window: MainWindow, make_pdf: PageMaker) -> None:
        window._loaded(load(make_pdf(4)))
        wait_until(lambda: len(window._thumbnails) == 4)
        assert set(window._thumbnails) == {0, 1, 2, 3}

    def test_an_edit_while_loading_does_not_ask_for_a_page_twice(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        asked_for: list[int] = []
        window._render_requested.connect(lambda _generation, page, _width: asked_for.append(page))

        window._loaded(load(make_pdf(3)))
        window._populate_grid()  # what a reorder does, before anything has arrived

        assert sorted(asked_for) == [0, 1, 2]

    def test_closing_mid_render_stops_the_thread(self, make_pdf: PageMaker) -> None:
        made = MainWindow()
        made._loaded(load(make_pdf(40)))  # far more queued than can finish instantly
        made.close()
        assert made._render_thread.isFinished()


class TestStaleResults:
    def test_a_result_for_the_previous_document_is_dropped(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(2, name="first.pdf")))
        previous = window._thumbnail_generation
        window._loaded(load(make_pdf(2, name="second.pdf")))

        window._thumbnail_ready(previous, 0, QImage(10, 10, QImage.Format.Format_RGBA8888))

        assert window._thumbnails == {}

    def test_changing_size_re_renders_everything_at_the_new_width(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(3)))
        wait_until(lambda: len(window._thumbnails) == 3)

        window._set_thumbnail_size("large")
        wait_until(lambda: len(window._thumbnails) == 3)

        assert {pixmap.width() for pixmap in window._thumbnails.values()} == {232}

    def test_the_renderer_skips_a_request_from_an_old_generation(self, make_pdf: PageMaker) -> None:
        """Called directly here on purpose — no thread — to check the skip
        itself rather than the queueing around it."""
        renderer = ThumbnailRenderer()
        renderer.open(str(make_pdf(2)), None)
        delivered: list[tuple[int, int]] = []
        renderer.rendered.connect(
            lambda generation, page, _image: delivered.append((generation, page))
        )
        renderer.wanted_generation = 2

        renderer.render(1, 0, 50)  # superseded while queued
        renderer.render(2, 1, 50)

        assert delivered == [(2, 1)]
        renderer.close()


class TestPdfiumIsNeverEnteredFromTwoThreads:
    """PDFium is not thread-safe, even across unrelated documents; see
    `modpdf.pdfium_lock`. Once thumbnails really did render on their own
    thread, the rest of the suite reading a PDF's text on the main thread
    at the same moment crashed the whole process."""

    def test_the_renderer_waits_while_someone_else_holds_the_lock(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        with PDFIUM_LOCK:
            window._loaded(load(make_pdf(2)))
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            assert window._thumbnails == {}  # blocked, not racing

        wait_until(lambda: len(window._thumbnails) == 2)
