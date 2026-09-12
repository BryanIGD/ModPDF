"""Rendering page thumbnails, off the user interface thread.

The renderer owns its PDFium document and lives on a single worker thread, so
the document is only ever touched from one place. Requests arrive as queued
signals and results come back the same way.

Rendered pages are held in memory and never written to disk. A thumbnail cache
is a folder of readable pictures of someone's confidential documents, sitting
outside whatever protection the original had, and it would outlive the session
that made it. The cost of re-rendering on next launch is worth not doing that.
"""

from __future__ import annotations

import pypdfium2
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

__all__ = ["THUMBNAIL_WIDTH", "ThumbnailRenderer"]

THUMBNAIL_WIDTH = 168


class ThumbnailRenderer(QObject):
    """Renders single pages to images. Move it to a QThread before using it."""

    rendered = Signal(int, QImage)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._document: pypdfium2.PdfDocument | None = None

    @Slot(str, object)
    def open(self, path: str, password: object) -> None:
        self.close()
        try:
            self._document = pypdfium2.PdfDocument(path, password=password)
        except Exception as exc:  # PDFium raises a variety of types
            self._document = None
            self.failed.emit(f"cannot render pages: {exc}")

    @Slot(int, int)
    def render(self, index: int, width: int) -> None:
        """Render one page of the source document at roughly `width` pixels."""
        document = self._document
        if document is None or not 0 <= index < len(document):
            return

        try:
            page = document[index]
            page_width = page.get_size()[0] or 612.0
            bitmap = page.render(scale=width / page_width)
            image = bitmap.to_pil().convert("RGBA")
        except Exception as exc:
            self.failed.emit(f"cannot render page {index + 1}: {exc}")
            return

        # QImage does not take ownership of the buffer, so copy before the
        # Python bytes object goes out of scope and the pixels vanish.
        frame = QImage(
            image.tobytes("raw", "RGBA"),
            image.width,
            image.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self.rendered.emit(index, frame)

    @Slot()
    def close(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None


def placeholder(width: int = THUMBNAIL_WIDTH) -> QPixmap:
    """A blank page-shaped tile to show while a real thumbnail is rendering."""
    height = round(width * 11 / 8.5)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.white)
    return pixmap
