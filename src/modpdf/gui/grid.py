"""The page thumbnail grid.

Reordering here is ordinary mouse tracking, not Qt's built-in item
drag-and-drop, for two reasons found by hand.

First, Qt's own internal move implements a drag as remove-then-insert. On a
plain icon-mode list that drops the moved page on top of whatever was already
at the target: dragging page 3 into the gap between pages 5 and 6 destroyed
page 6 and left two copies of page 3.

Second, and more basic: that machinery goes through `QDrag`, which needs
platform-level support to run a native drag session at all. A real simulated
mouse press-move-release through it produced no `dropEvent` whatsoever — the
session simply never started. Ordinary mouse events carry no such platform
dependency, which is also what makes this reordering something a test can
drive directly rather than trust.

Nothing is inserted or removed until the button comes up. Until then this
widget only tracks where the cursor is and paints where the drop would land;
the window performs the actual move in the page ordering once it knows where
the drop landed.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QListWidget

__all__ = ["PAGE_ROLE", "PageGrid"]

# Each tile remembers which page of the source document it shows.
PAGE_ROLE = Qt.ItemDataRole.UserRole

# Kept as a plain string rather than importing modpdf.gui.theme, so this widget
# does not need to know about the application's palette module to draw itself.
_MARK_BLUE = "#5B82B0"


class PageGrid(QListWidget):
    """Thumbnails of the pages, rearranged by dragging them with the mouse."""

    pages_moved = Signal(list, int)

    def __init__(self, thumbnail_width: int) -> None:
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(thumbnail_width, round(thumbnail_width * 11 / 8.5)))
        self.setSpacing(10)
        self.setUniformItemSizes(True)

        # No native drag-and-drop; see the module docstring for why.
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)

        self._press_point: QPoint | None = None
        self._dragging = False
        self._drag_positions: list[int] = []
        self._drop_gap = 0

    def page_order(self) -> list[int]:
        """The source page behind each tile, in the order shown."""
        return [self.item(row).data(PAGE_ROLE) for row in range(self.count())]

    # ------------------------------------------------------------- dragging

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Run first, so Qt's own selection handling — click an unselected tile
        # to select just it, click one already in a multi-selection and defer
        # the change in case a drag follows — is in place before anything here
        # reads the selection.
        super().mousePressEvent(event)
        self._press_point = (
            event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        )
        self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_point is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        here = event.position().toPoint()

        if not self._dragging:
            moved = (here - self._press_point).manhattanLength()
            if moved < QApplication.startDragDistance():
                return  # a click, or not yet decisively a drag
            self._begin_drag(here)
        else:
            self._drop_gap = self.gap_at(here)
            self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_point = None
        if not self._dragging:
            super().mouseReleaseEvent(event)
            return

        self._dragging = False
        self.unsetCursor()
        self.viewport().update()

        positions, gap = self._drag_positions, self._drop_gap
        self._drag_positions = []
        if positions:
            self.pages_moved.emit(positions, gap)

    def _begin_drag(self, point: QPoint) -> None:
        """A press-and-move past the threshold: start moving the selection.

        Whatever is selected right now is what moves, which — because
        `super().mousePressEvent` already ran — correctly includes a
        multi-page selection built with Shift or Ctrl before the drag began.
        """
        self._dragging = True
        self._drag_positions = sorted(index.row() for index in self.selectedIndexes())
        self._drop_gap = self.gap_at(point)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.viewport().update()

    def gap_at(self, point: QPoint) -> int:
        """Which gap between pages `point` is closest to, 0 .. count().

        The page lands before the first tile whose midpoint the point has not
        yet passed, reading left to right and top to bottom — so the left half
        of a tile means "before this one" and the right half means "after",
        and a point above every tile, or left of all of them, means the very
        front.
        """
        for row in range(self.count()):
            rect = self.visualItemRect(self.item(row))
            if point.y() < rect.top():
                return row
            on_this_line = rect.top() <= point.y() <= rect.bottom()
            if on_this_line and point.x() < rect.center().x():
                return row
        return self.count()

    # --------------------------------------------------------------- paint

    def paintEvent(self, event: object) -> None:
        super().paintEvent(event)  # type: ignore[arg-type]
        if not self._dragging:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tint = QColor(_MARK_BLUE)
        tint.setAlpha(46)
        for row in self._drag_positions:
            item = self.item(row)
            if item is not None:
                painter.fillRect(self.visualItemRect(item), tint)

        x, top, bottom = self._gap_edge(self._drop_gap)
        if x is not None:
            pen = painter.pen()
            pen.setColor(QColor(_MARK_BLUE))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawLine(x, top, x, bottom)
        painter.end()

    def _gap_edge(self, gap: int) -> tuple[int | None, int, int]:
        """The vertical line marking one gap: its x position and y span."""
        if self.count() == 0:
            return None, 0, 0
        if gap < self.count():
            rect = self.visualItemRect(self.item(gap))
            return rect.left(), rect.top(), rect.bottom()
        rect = self.visualItemRect(self.item(self.count() - 1))
        return rect.right(), rect.top(), rect.bottom()
