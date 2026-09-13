"""The small line icons used next to tool tabs and action buttons.

Drawn rather than loaded from files, for the same reason as the app mark in
`widgets.py`: no asset file to ship or go stale, and they stay sharp at any
size. Every icon is stroked in a 24x24 unit space at 4x supersampling, then
downscaled — plain geometry (lines, circles, simple paths), not an attempt at
a pixel-perfect icon-font clone.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

from modpdf.gui import theme

__all__ = ["icon", "icon_pixmap"]

At = Callable[[float, float], tuple[float, float]]
_Draw = Callable[[QPainter, At, float], None]


def icon(name: str, *, size: int = 16, color: str = theme.INK_2) -> QIcon:
    """A `QIcon` wrapping `icon_pixmap`, ready for `QPushButton.setIcon`."""
    result = QIcon()
    result.addPixmap(icon_pixmap(name, size=size, color=color))
    return result


def icon_pixmap(name: str, *, size: int = 16, color: str = theme.INK_2) -> QPixmap:
    draw = _ICONS[name]
    scale = 4  # draw large and downscale, for clean edges at small sizes
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size * scale / 24.0

    def at(x: float, y: float) -> tuple[float, float]:
        return x * unit, y * unit

    pen = painter.pen()
    pen.setColor(QColor(color))
    pen.setWidthF(1.8 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    draw(painter, at, unit)

    painter.end()
    return canvas.scaled(
        QSize(size, size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _path(at: At, *points: tuple[float, float], close: bool = False) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*at(*points[0]))
    for point in points[1:]:
        path.lineTo(*at(*point))
    if close:
        path.closeSubpath()
    return path


def _draw_folder(painter: QPainter, at: At, unit: float) -> None:
    painter.drawPath(
        _path(at, (3, 7), (3, 19), (21, 19), (21, 9), (11, 9), (9, 6), (3, 6), close=True)
    )


def _draw_document(painter: QPainter, at: At, unit: float) -> None:
    painter.drawPath(_path(at, (6, 3), (14, 3), (18, 7), (18, 21), (6, 21), close=True))
    painter.drawPath(_path(at, (14, 3), (14, 7), (18, 7)))


def _draw_scissors(painter: QPainter, at: At, unit: float) -> None:
    painter.drawEllipse(QPointF(*at(6.2, 18.2)), 2.3 * unit, 2.3 * unit)
    painter.drawEllipse(QPointF(*at(6.2, 6.8)), 2.3 * unit, 2.3 * unit)
    painter.drawPath(_path(at, (8.1, 8.1), (20, 19.3)))
    painter.drawPath(_path(at, (8.1, 16.9), (20, 5.7)))


def _draw_compress(painter: QPainter, at: At, unit: float) -> None:
    """Two chevrons pointing toward each other — the shape most compress
    icons use, distinct from the outward-pointing arrows an "expand" icon
    would draw."""
    painter.drawPath(_path(at, (7, 10), (12, 5), (17, 10)))
    painter.drawPath(_path(at, (7, 14), (12, 19), (17, 14)))


def _draw_shield(painter: QPainter, at: At, unit: float) -> None:
    path = QPainterPath()
    path.moveTo(*at(12, 2.5))
    path.lineTo(*at(20, 5.5))
    path.lineTo(*at(20, 11))
    path.cubicTo(*at(20, 17), *at(16.5, 20.5), *at(12, 22))
    path.cubicTo(*at(7.5, 20.5), *at(4, 17), *at(4, 11))
    path.lineTo(*at(4, 5.5))
    path.closeSubpath()
    painter.drawPath(path)


def _draw_list(painter: QPainter, at: At, unit: float) -> None:
    for y in (6, 12, 18):
        painter.drawEllipse(QPointF(*at(4, y)), 1.0 * unit, 1.0 * unit)
        painter.drawPath(_path(at, (8, y), (21, y)))


def _draw_gear(painter: QPainter, at: At, unit: float) -> None:
    center = QPointF(*at(12, 12))
    painter.drawEllipse(center, 4.2 * unit, 4.2 * unit)
    painter.save()
    painter.translate(center)
    for tooth in range(8):
        painter.save()
        painter.rotate(tooth * 45)
        painter.drawLine(QPointF(0, -7.4 * unit), QPointF(0, -9.6 * unit))
        painter.restore()
    painter.restore()


def _draw_info(painter: QPainter, at: At, unit: float) -> None:
    painter.drawEllipse(QPointF(*at(12, 12)), 9 * unit, 9 * unit)
    painter.drawPath(_path(at, (12, 11), (12, 16.5)))
    dot_pen = painter.pen()
    dot_pen.setWidthF(2.4 * unit)
    painter.setPen(dot_pen)
    painter.drawPoint(QPointF(*at(12, 7.6)))


def _draw_export(painter: QPainter, at: At, unit: float) -> None:
    """A page with an arrow leaving it — "take these pages out"."""
    painter.drawPath(_path(at, (5, 3), (11.5, 3), (14, 5.5), (14, 21), (5, 21), close=True))
    painter.drawPath(_path(at, (11.5, 3), (11.5, 5.5), (14, 5.5)))
    painter.drawPath(_path(at, (16, 15), (21, 11), (16, 7)))
    painter.drawPath(_path(at, (10, 11), (21, 11)))


def _draw_trash(painter: QPainter, at: At, unit: float) -> None:
    painter.drawPath(_path(at, (4, 7), (20, 7)))
    painter.drawPath(_path(at, (9, 7), (9, 4), (15, 4), (15, 7)))
    painter.drawPath(_path(at, (6, 7), (7, 21), (17, 21), (18, 7)))
    painter.drawPath(_path(at, (10, 10.5), (10, 17.5)))
    painter.drawPath(_path(at, (14, 10.5), (14, 17.5)))


def _draw_copy(painter: QPainter, at: At, unit: float) -> None:
    painter.drawPath(_path(at, (8, 8), (8, 20), (18, 20), (18, 8), close=True))
    painter.drawPath(_path(at, (6, 16), (4, 16), (4, 4), (14, 4), (14, 6)))


_ICONS: dict[str, _Draw] = {
    "folder": _draw_folder,
    "document": _draw_document,
    "scissors": _draw_scissors,
    "compress": _draw_compress,
    "shield": _draw_shield,
    "list": _draw_list,
    "gear": _draw_gear,
    "info": _draw_info,
    "export": _draw_export,
    "trash": _draw_trash,
    "copy": _draw_copy,
}
