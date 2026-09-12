"""Small pieces of chrome shared by the window."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from modpdf.gui import theme

__all__ = ["Chip", "RangeRow", "SectionLabel", "app_icon", "mark_pixmap"]


def mark_pixmap(size: int = 20) -> QPixmap:
    """The application mark: the icon's hexagon, a document, a blue fold.

    Drawn rather than loaded so it stays sharp at any size and needs no asset
    file on disk.
    """
    scale = 4  # draw large and downscale, for clean edges at small sizes
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size * scale / 24.0

    def at(x: float, y: float) -> tuple[float, float]:
        return x * unit, y * unit

    hexagon = QPainterPath()
    points = [(12, 2.4), (19.9, 7.2), (19.9, 16.8), (12, 21.6), (4.1, 16.8), (4.1, 7.2)]
    hexagon.moveTo(*at(*points[0]))
    for point in points[1:]:
        hexagon.lineTo(*at(*point))
    hexagon.closeSubpath()

    pen = painter.pen()
    pen.setColor(QColor(theme.SLATE))
    pen.setWidthF(2.0 * unit)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(hexagon)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.SLATE))
    document = QPainterPath()
    document.moveTo(*at(9.4, 8.5))
    document.lineTo(*at(12.7, 8.5))
    document.lineTo(*at(14.7, 10.5))
    document.lineTo(*at(14.7, 16.4))
    document.lineTo(*at(9.4, 16.4))
    document.closeSubpath()
    painter.drawPath(document)

    painter.setBrush(QColor(theme.BLUE))
    fold = QPainterPath()
    fold.moveTo(*at(12.7, 8.5))
    fold.lineTo(*at(12.7, 10.5))
    fold.lineTo(*at(14.7, 10.5))
    fold.closeSubpath()
    painter.drawPath(fold)
    painter.end()

    return canvas.scaled(
        QSize(size, size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 64, 128):
        icon.addPixmap(mark_pixmap(size))
    return icon


class SectionLabel(QLabel):
    """The small uppercase heading used down the inspector."""

    def __init__(self, text: str) -> None:
        super().__init__(text.upper())
        self.setStyleSheet(
            f"color: {theme.INK_3}; font-size: 10px; font-weight: 700;"
            " letter-spacing: 0.7px; background: transparent;"
        )


class Chip(QWidget):
    """A rounded status pill. Used for the safety summary in the header."""

    def __init__(self) -> None:
        super().__init__()
        self._label = QLabel()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.addWidget(self._label)
        self.hide()

    def show_state(self, text: str, *, tone: str) -> None:
        """Tone is one of good, warn, bad — safety meanings only."""
        colors = {
            "good": (theme.GOOD, theme.GOOD_SOFT, theme.GOOD_LINE),
            "warn": (theme.WARN, theme.WARN_SOFT, theme.WARN_LINE),
            "bad": (theme.BAD, theme.BAD_SOFT, theme.BAD_LINE),
        }
        ink, fill, line = colors[tone]
        self.setStyleSheet(f"background: {fill}; border: 1px solid {line}; border-radius: 11px;")
        self._label.setStyleSheet(
            f"color: {ink}; font-size: 11px; font-weight: 600; background: transparent;"
        )
        self._label.setText(text)
        self.show()


class RangeRow(QWidget):
    """One "pages Start to End" row in the split panel's range editor.

    Values are page numbers as a person reads them — 1-based, inclusive at
    both ends — and are counted against the document as currently shown, not
    against the original file, so they mean the same pages the range preview
    and the page grid agree on.
    """

    changed = Signal()
    removed = Signal(object)

    def __init__(self, maximum: int, start: int = 1, end: int = 1) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        row.addWidget(QLabel("Pages"))
        self.start = QSpinBox()
        row.addWidget(self.start)
        row.addWidget(QLabel("to"))
        self.end = QSpinBox()
        row.addWidget(self.end)
        row.addStretch(1)

        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self.removed.emit(self))
        row.addWidget(remove)

        self.set_maximum(maximum)
        self.start.setValue(min(start, self.start.maximum()))
        self.end.setValue(min(end, self.end.maximum()))
        self.start.valueChanged.connect(self.changed)
        self.end.valueChanged.connect(self.changed)

    def set_maximum(self, maximum: int) -> None:
        """Keep the spin boxes in step with however many pages exist right now."""
        ceiling = max(maximum, 1)
        self.start.setRange(1, ceiling)
        self.end.setRange(1, ceiling)

    def value(self) -> tuple[int, int]:
        return self.start.value(), self.end.value()
