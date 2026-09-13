"""Small pieces of chrome shared by the window."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from modpdf.gui import theme

__all__ = [
    "Chip",
    "RangeRow",
    "SectionLabel",
    "SegmentedControl",
    "ThemeToggle",
    "app_icon",
    "mark_pixmap",
]


def mark_pixmap(size: int = 20, *, ink_color: str | None = None) -> QPixmap:
    """The application mark: the icon's hexagon, a document, a blue fold.

    Drawn rather than loaded so it stays sharp at any size and needs no asset
    file on disk.

    `ink_color` defaults to `theme.SLATE` — the one colour `theme.set_mode`
    never changes — because `app_icon()` uses this for the OS taskbar/dock
    icon, which sits on the operating system's own chrome, not this app's, and
    has no business following our in-window light/dark setting. Callers
    drawing the mark *inside* the window (the header, the empty-state
    illustration) pass `theme.INK` explicitly instead, so it stays legible
    against whichever theme is actually active.
    """
    scale = 4  # draw large and downscale, for clean edges at small sizes
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size * scale / 24.0
    ink = ink_color if ink_color is not None else theme.SLATE

    def at(x: float, y: float) -> tuple[float, float]:
        return x * unit, y * unit

    hexagon = QPainterPath()
    points = [(12, 2.4), (19.9, 7.2), (19.9, 16.8), (12, 21.6), (4.1, 16.8), (4.1, 7.2)]
    hexagon.moveTo(*at(*points[0]))
    for point in points[1:]:
        hexagon.lineTo(*at(*point))
    hexagon.closeSubpath()

    pen = painter.pen()
    pen.setColor(QColor(ink))
    pen.setWidthF(2.0 * unit)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(hexagon)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ink))
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


class ThemeToggle(QWidget):
    """A two-position Light/Dark slider, for the Settings dialog.

    Drawn rather than assembled from stock widgets, for the same reason as
    `mark_pixmap`: a sliding pill with an animated knob isn't something Qt's
    stock controls give you directly, and this needs no new dependency to
    draw. Exposes the same small surface a `QCheckBox` would (`isChecked`,
    `setChecked`, a `toggled(bool)` signal) — `True` meaning dark — so it
    drops into `_show_settings` the same way a checkbox would have.
    """

    toggled = Signal(bool)

    _WIDTH = 172
    _HEIGHT = 32
    _PAD = 3

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dark = False
        self._knob_x = float(self._PAD)

        half = self._WIDTH // 2
        self._light_label = QLabel("Light", self)
        self._light_label.setGeometry(0, 0, half, self._HEIGHT)
        self._dark_label = QLabel("Dark", self)
        self._dark_label.setGeometry(half, 0, self._WIDTH - half, self._HEIGHT)
        for label in (self._light_label, self._dark_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._animation = QPropertyAnimation(self, b"knob_x")
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._update_labels()

    def isChecked(self) -> bool:
        return self._dark

    def setChecked(self, dark: bool) -> None:
        if dark == self._dark:
            return
        self._dark = dark
        self._animation.stop()
        self._animation.setStartValue(self._knob_x)
        self._animation.setEndValue(self._knob_target())
        self._animation.start()
        self._update_labels()
        self.toggled.emit(dark)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setChecked(not self._dark)
        super().mousePressEvent(event)

    def _knob_target(self) -> float:
        knob_width = self._WIDTH // 2 - self._PAD * 2
        return float(self._WIDTH - self._PAD - knob_width) if self._dark else float(self._PAD)

    def _get_knob_x(self) -> float:
        return self._knob_x

    def _set_knob_x(self, value: float) -> None:
        self._knob_x = value
        self.update()

    knob_x = Property(float, _get_knob_x, _set_knob_x)

    def _update_labels(self) -> None:
        active = "color: #FFFFFF; font-size: 12px; font-weight: 700; background: transparent;"
        inactive = (
            f"color: {theme.INK_3}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        self._light_label.setStyleSheet(inactive if self._dark else active)
        self._dark_label.setStyleSheet(active if self._dark else inactive)

    def refresh_theme(self) -> None:
        """Re-read the current palette without changing which side is
        picked. This widget lives in the Settings dialog, which sits outside
        the window's central widget and so is not rebuilt by
        `MainWindow._apply_theme` — it needs to be told directly, the same
        as `SectionLabel.refresh_theme`."""
        self._update_labels()
        self.update()

    def paintEvent(self, event: object) -> None:
        del event  # unused; QPainter targets the whole widget regardless
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor(theme.RAIL))
        painter.drawRoundedRect(0, 0, self._WIDTH, self._HEIGHT, self._HEIGHT / 2, self._HEIGHT / 2)

        knob_width = self._WIDTH // 2 - self._PAD * 2
        knob_height = self._HEIGHT - self._PAD * 2
        painter.setBrush(QColor(theme.BLUE))
        painter.drawRoundedRect(
            int(self._knob_x), self._PAD, knob_width, knob_height, knob_height / 2, knob_height / 2
        )
        painter.end()


class SegmentedControl(QWidget):
    """A row of mutually exclusive text options with a sliding highlight —
    the same drawing as `ThemeToggle`, generalized past a plain on/off
    choice. Used in the Settings dialog for "pick one of a short, named
    list" preferences (thumbnail size, default compression level).

    Kept as its own class rather than rewriting `ThemeToggle` on top of it:
    that widget's `isChecked`/`setChecked`/`toggled(bool)` surface mirrors
    `QCheckBox` on purpose, and reshaping it into a string-based control
    would touch its call sites and tests for no behavioural gain.
    """

    changed = Signal(str)

    _HEIGHT = 32
    _PAD = 3

    def __init__(self, options: list[str], *, segment_width: int = 96) -> None:
        super().__init__()
        if len(options) < 2:
            raise ValueError("a segmented control needs at least two options")
        self._options = options
        self._segment_width = segment_width
        self._index = 0
        self._knob_x = float(self._PAD)

        self.setFixedSize(segment_width * len(options), self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._labels = [QLabel(option, self) for option in options]
        for i, label in enumerate(self._labels):
            label.setGeometry(i * segment_width, 0, segment_width, self._HEIGHT)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._animation = QPropertyAnimation(self, b"knob_x")
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._update_labels()

    def currentValue(self) -> str:
        return self._options[self._index]

    def setCurrentValue(self, value: str) -> None:
        index = self._options.index(value)
        if index == self._index:
            return
        self._index = index
        self._animation.stop()
        self._animation.setStartValue(self._knob_x)
        self._animation.setEndValue(self._knob_target())
        self._animation.start()
        self._update_labels()
        self.changed.emit(value)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        index = min(max(x // self._segment_width, 0), len(self._options) - 1)
        self.setCurrentValue(self._options[index])
        super().mousePressEvent(event)

    def _knob_target(self) -> float:
        return self._index * self._segment_width + self._PAD

    def _get_knob_x(self) -> float:
        return self._knob_x

    def _set_knob_x(self, value: float) -> None:
        self._knob_x = value
        self.update()

    knob_x = Property(float, _get_knob_x, _set_knob_x)

    def _update_labels(self) -> None:
        active = "color: #FFFFFF; font-size: 12px; font-weight: 700; background: transparent;"
        inactive = (
            f"color: {theme.INK_3}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        for i, label in enumerate(self._labels):
            label.setStyleSheet(active if i == self._index else inactive)

    def refresh_theme(self) -> None:
        """See `ThemeToggle.refresh_theme` — same reason."""
        self._update_labels()
        self.update()

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor(theme.RAIL))
        painter.drawRoundedRect(
            0, 0, self.width(), self._HEIGHT, self._HEIGHT / 2, self._HEIGHT / 2
        )

        knob_width = self._segment_width - self._PAD * 2
        knob_height = self._HEIGHT - self._PAD * 2
        painter.setBrush(QColor(theme.BLUE))
        painter.drawRoundedRect(
            int(self._knob_x), self._PAD, knob_width, knob_height, knob_height / 2, knob_height / 2
        )
        painter.end()


class SectionLabel(QLabel):
    """The small uppercase heading used down the inspector."""

    def __init__(self, text: str) -> None:
        super().__init__(text.upper())
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-read the current palette. Most instances are thrown away and
        rebuilt whenever the theme changes (see `MainWindow._apply_theme`),
        but one — in the Settings dialog itself — outlives the switch and
        needs to be told directly."""
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
