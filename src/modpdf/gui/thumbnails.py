"""Rendering page thumbnails, off the user interface thread.

The renderer owns its PDFium document and lives on a single worker thread, so
the document is only ever touched from one place. Requests arrive as queued
signals and results come back the same way — never as direct method calls
from the window, which would run on the window's own thread no matter which
thread this object was moved to, and freeze it for as long as a large document
takes to render.

Every render request carries a generation number, and so does every result.
Opening another document or changing the thumbnail size starts a new
generation; requests still queued from an older one are skipped rather than
rendered, and a result from one that finishes anyway is dropped by the window.
Without that, a slow first document could paint its pages onto the second
one's tiles.

Rendered pages are held in memory and never written to disk. A thumbnail cache
is a folder of readable pictures of someone's confidential documents, sitting
outside whatever protection the original had, and it would outlive the session
that made it. The cost of re-rendering on next launch is worth not doing that.
"""

from __future__ import annotations

from typing import cast

import pypdfium2
from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from modpdf.pdfium_lock import PDFIUM_LOCK

__all__ = ["THUMBNAIL_WIDTH", "ThumbnailRenderer"]

THUMBNAIL_WIDTH = 168


class ThumbnailRenderer(QObject):
    """Renders single pages to images. Move it to a QThread before using it."""

    rendered = Signal(int, int, QImage)  # generation, page index, image
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._document: pypdfium2.PdfDocument | None = None
        # Written by the window's thread, read by this one: a plain int, so a
        # read sees either the old value or the new one, never a torn one.
        # Queued requests below this generation are skipped without rendering.
        self.wanted_generation = 0

    @Slot(str, object)
    def open(self, path: str, password: object) -> None:
        self.close()
        error = None
        with PDFIUM_LOCK:
            try:
                self._document = pypdfium2.PdfDocument(path, password=password)
            except Exception as exc:  # PDFium raises a variety of types
                self._document = None
                error = f"cannot render pages: {exc}"
        if error is not None:
            self.failed.emit(error)

    @Slot(int, int, int)
    def render(self, generation: int, index: int, width: int) -> None:
        """Render one page of the source document at roughly `width` pixels."""
        if generation != self.wanted_generation:
            return  # superseded while it waited in the queue

        image = None
        error = None
        # One page at a time, so a compression's quality gate waiting for the
        # same lock gets its turn between pages rather than after all of them.
        with PDFIUM_LOCK:
            document = self._document
            if document is None or not 0 <= index < len(document):
                return
            try:
                image = _rasterise(document, index, width)
            except Exception as exc:  # PDFium raises a variety of types
                error = f"cannot render page {index + 1}: {exc}"
        if image is None:
            if error is not None:
                self.failed.emit(error)
            return

        # QImage does not take ownership of the buffer, so copy before the
        # Python bytes object goes out of scope and the pixels vanish.
        frame = QImage(
            image.tobytes("raw", "RGBA"),
            image.width,
            image.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self.rendered.emit(generation, index, frame)

    @Slot()
    def close(self) -> None:
        with PDFIUM_LOCK:
            if self._document is not None:
                self._document.close()
                self._document = None


def _rasterise(document: pypdfium2.PdfDocument, index: int, width: int) -> Image.Image:
    """Everything that touches PDFium for one thumbnail. Called with
    `PDFIUM_LOCK` held; the page and bitmap it creates are freed as it
    returns, so they are released while the lock is still held too."""
    page = document[index]
    page_width = page.get_size()[0] or 612.0
    bitmap = page.render(scale=width / page_width)
    # A copy, so nothing still points into PDFium once the bitmap is freed.
    return cast(Image.Image, bitmap.to_pil().convert("RGBA"))


def placeholder(width: int = THUMBNAIL_WIDTH) -> QPixmap:
    """A blank page-shaped tile to show while a real thumbnail is rendering."""
    height = round(width * 11 / 8.5)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.white)
    return pixmap
