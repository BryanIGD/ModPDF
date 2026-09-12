"""Tests for dragging pages into a new order.

Two layers, tested separately and then together:

- `Session.move` is the rule — positions and an insertion point — checked
  exhaustively without any widget at all.
- `PageGrid` is the mouse tracking that decides what positions and insertion
  point a real drag means, checked with genuine `QMouseEvent` press/move/release
  sequences rather than by calling its signal directly.

That second layer is the one a previous pass got wrong: it emitted
`pages_moved` by hand and never drove an actual mouse gesture through the
widget, so a real drag failing silently would not have failed the tests
either. `TestRealMouseDrag` below is the fix for that gap, not just for the
drag itself.

Page numbers in these tests are 1-based, the way someone looking at the window
counts them; the session stores 0-based indices.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QListWidgetItem

from modpdf.gui.grid import PAGE_ROLE, PageGrid
from modpdf.gui.session import Session, load
from modpdf.gui.thumbnails import THUMBNAIL_WIDTH, placeholder
from modpdf.gui.window import MainWindow
from tests.conftest import PageMaker, page_markers

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def session(make_pdf: PageMaker) -> Session:
    return load(make_pdf(6, name="doc.pdf"))


def shown(session: Session) -> list[int]:
    """The page numbers as the window would label them, 1-based."""
    return [page + 1 for page in session.order]


# --------------------------------------------------------------------------
# Session.move: the rule itself, no widget involved.
# --------------------------------------------------------------------------


class TestTheGestureFromTheBrief:
    def test_page_3_dropped_between_5_and_6(self, session: Session) -> None:
        """Grab page 3, drop it in the gap between pages 5 and 6."""
        session.move([2], 5)
        assert shown(session) == [1, 2, 4, 5, 3, 6]

    def test_and_it_survives_a_save(self, session: Session, tmp_path: Path) -> None:
        session.move([2], 5)
        out = session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [1, 2, 4, 5, 3, 6]


class TestMovingOnePage:
    def test_to_the_very_front(self, session: Session) -> None:
        session.move([3], 0)
        assert shown(session) == [4, 1, 2, 3, 5, 6]

    def test_to_the_very_end(self, session: Session) -> None:
        session.move([0], 6)
        assert shown(session) == [2, 3, 4, 5, 6, 1]

    def test_backwards(self, session: Session) -> None:
        """Page 5 dropped into the gap between pages 1 and 2."""
        session.move([4], 1)
        assert shown(session) == [1, 5, 2, 3, 4, 6]

    def test_one_step_right(self, session: Session) -> None:
        session.move([0], 2)
        assert shown(session) == [2, 1, 3, 4, 5, 6]

    def test_dropping_a_page_where_it_already_is_changes_nothing(self, session: Session) -> None:
        session.move([2], 2)
        assert shown(session) == [1, 2, 3, 4, 5, 6]
        session.move([2], 3)
        assert shown(session) == [1, 2, 3, 4, 5, 6]


class TestMovingSeveralPages:
    def test_a_contiguous_block_keeps_its_internal_order(self, session: Session) -> None:
        session.move([0, 1], 5)
        assert shown(session) == [3, 4, 5, 1, 2, 6]

    def test_a_scattered_selection_is_gathered(self, session: Session) -> None:
        """Pages 1, 3 and 5 dropped together land as a block, in page order."""
        session.move([0, 2, 4], 6)
        assert shown(session) == [2, 4, 6, 1, 3, 5]

    def test_a_block_moved_to_the_front(self, session: Session) -> None:
        session.move([3, 4, 5], 0)
        assert shown(session) == [4, 5, 6, 1, 2, 3]


class TestWhereItLands:
    def test_reports_the_landing_position(self, session: Session) -> None:
        """So the window can leave the dragged pages selected."""
        assert session.move([2], 5) == 4
        assert shown(session)[4] == 3

    def test_landing_position_for_a_block(self, session: Session) -> None:
        landed = session.move([0, 1], 5)
        assert landed == 3
        assert shown(session)[3:5] == [1, 2]

    def test_moving_to_the_front_lands_at_zero(self, session: Session) -> None:
        assert session.move([4], 0) == 0


class TestRefusals:
    def test_an_insertion_point_past_the_end(self, session: Session) -> None:
        with pytest.raises(ValueError, match="cannot insert at 9"):
            session.move([0], 9)

    def test_a_negative_insertion_point(self, session: Session) -> None:
        with pytest.raises(ValueError, match="cannot insert"):
            session.move([0], -1)

    def test_moving_a_page_that_is_not_there(self, session: Session) -> None:
        with pytest.raises(ValueError, match="not in the document"):
            session.move([99], 0)

    def test_moving_nothing_is_harmless(self, session: Session) -> None:
        session.move([], 3)
        assert shown(session) == [1, 2, 3, 4, 5, 6]


class TestNoPageIsEverLost:
    """The failure that mattered first: Qt's own move destroyed the page it landed on."""

    @pytest.mark.parametrize("before", range(7))
    @pytest.mark.parametrize("grab", range(6))
    def test_every_single_page_move_keeps_all_six(
        self, session: Session, grab: int, before: int
    ) -> None:
        session.move([grab], before)
        assert sorted(session.order) == [0, 1, 2, 3, 4, 5], "a page was lost or duplicated"
        assert len(session.order) == 6

    @pytest.mark.parametrize("before", range(7))
    def test_every_block_move_keeps_all_six(self, session: Session, before: int) -> None:
        session.move([1, 2], before)
        assert sorted(session.order) == [0, 1, 2, 3, 4, 5]


# --------------------------------------------------------------------------
# PageGrid: a real mouse, driven through actual QMouseEvent objects.
# --------------------------------------------------------------------------


def _mouse_event(
    kind: QEvent.Type,
    point: QPoint,
    *,
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    buttons: Qt.MouseButton = Qt.MouseButton.LeftButton,
) -> QMouseEvent:
    # The local-position-only overload is deprecated in this Qt version; the
    # widget only ever reads the local position, so the global one is a copy.
    local = QPointF(point)
    return QMouseEvent(kind, local, local, button, buttons, Qt.KeyboardModifier.NoModifier)


def _settle() -> None:
    """Pump the event loop briefly so a freshly shown widget has its layout."""
    loop = QEventLoop()
    QTimer.singleShot(150, loop.quit)
    loop.exec()


def _drag(grid: PageGrid, start: QPoint, end: QPoint) -> None:
    """A real press, a move past the drag threshold, another move, then release.

    The two-step move matters: the first is what crosses
    `QApplication.startDragDistance()` and flips the grid into dragging mode,
    the second is what the drop actually lands on. Skipping straight from press
    to the final point would never exercise that transition.
    """
    midpoint = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    grid.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, start))
    grid.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, midpoint))
    grid.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, end))
    grid.mouseReleaseEvent(
        _mouse_event(QEvent.Type.MouseButtonRelease, end, buttons=Qt.MouseButton.NoButton)
    )


@pytest.fixture
def grid() -> Iterator[PageGrid]:
    made = PageGrid(THUMBNAIL_WIDTH)
    for page in range(6):
        tile = QListWidgetItem(str(page + 1))
        tile.setData(PAGE_ROLE, page)
        tile.setIcon(placeholder())
        made.addItem(tile)
    made.resize(1000, 700)
    made.show()
    _settle()
    yield made
    made.close()


class TestRealMouseDrag:
    """A genuine press-move-release sequence, not a hand-emitted signal.

    This is the layer the previous pass never actually exercised: its tests
    called `grid.pages_moved.emit(...)` directly, which proves the window
    responds correctly to the signal but proves nothing about whether an
    actual drag produces it.
    """

    def test_the_exact_gesture_from_the_brief(self, grid: PageGrid) -> None:
        """Grab page 3, drop it in the gap between pages 5 and 6."""
        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        start = grid.visualItemRect(grid.item(2)).center()
        target = grid.visualItemRect(grid.item(4))
        end = QPoint(target.right() - 5, target.center().y())
        _drag(grid, start, end)

        assert moved == [([2], 5)]

    def test_dragging_to_the_very_front(self, grid: PageGrid) -> None:
        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        start = grid.visualItemRect(grid.item(3)).center()
        front = grid.visualItemRect(grid.item(0))
        end = QPoint(front.left() + 3, start.y())
        _drag(grid, start, end)

        assert moved == [([3], 0)]

    def test_dragging_to_the_very_end(self, grid: PageGrid) -> None:
        """Page 6 sits on a second row once 6 tiles no longer fit one line."""
        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        start = grid.visualItemRect(grid.item(0)).center()
        last = grid.visualItemRect(grid.item(5))
        end = QPoint(last.right() - 3, last.center().y())
        _drag(grid, start, end)

        assert moved == [([0], 6)]

    def test_dragging_across_a_row_wrap(self, grid: PageGrid) -> None:
        start = grid.visualItemRect(grid.item(3)).center()
        second_row = grid.visualItemRect(grid.item(5))
        end = QPoint(second_row.left() + 10, second_row.center().y())

        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))
        _drag(grid, start, end)

        assert moved
        positions, gap = moved[0]
        assert positions == [3]
        assert gap <= 5

    def test_a_click_with_no_movement_emits_nothing(self, grid: PageGrid) -> None:
        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        point = grid.visualItemRect(grid.item(1)).center()
        grid.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, point))
        grid.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, point, buttons=Qt.MouseButton.NoButton)
        )

        assert moved == []

    def test_a_plain_click_still_selects_normally(self, grid: PageGrid) -> None:
        """Dropping Qt's native drag machinery must not cost ordinary selection."""
        point = grid.visualItemRect(grid.item(1)).center()
        grid.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, point))
        grid.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, point, buttons=Qt.MouseButton.NoButton)
        )
        assert [index.row() for index in grid.selectedIndexes()] == [1]

    def test_a_small_jitter_is_not_a_drag(self, grid: PageGrid) -> None:
        """Movement under the platform's drag threshold must still count as a click."""
        point = grid.visualItemRect(grid.item(1)).center()
        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        grid.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, point))
        grid.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, point + QPoint(1, 0)))
        grid.mouseReleaseEvent(
            _mouse_event(
                QEvent.Type.MouseButtonRelease,
                point + QPoint(1, 0),
                buttons=Qt.MouseButton.NoButton,
            )
        )

        assert moved == []

    def test_dragging_a_multi_selection_moves_the_whole_group(self, grid: PageGrid) -> None:
        """Selection made before the drag (Ctrl/Shift-click) must survive the press."""
        grid.item(0).setSelected(True)
        grid.item(2).setSelected(True)

        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        start = grid.visualItemRect(grid.item(2)).center()  # press on one already-selected tile
        last = grid.visualItemRect(grid.item(5))
        end = QPoint(last.right() - 3, last.center().y())
        _drag(grid, start, end)

        assert moved == [([0, 2], 6)]

    def test_dragging_an_unselected_page_moves_only_that_page(self, grid: PageGrid) -> None:
        """Pressing outside the current selection replaces it, as a plain click does."""
        grid.item(0).setSelected(True)
        grid.item(2).setSelected(True)

        moved = []
        grid.pages_moved.connect(lambda positions, gap: moved.append((positions, gap)))

        start = grid.visualItemRect(grid.item(4)).center()  # not part of the prior selection
        front = grid.visualItemRect(grid.item(0))
        end = QPoint(front.left() + 3, start.y())
        _drag(grid, start, end)

        assert moved == [([4], 0)]

    def test_a_paint_during_the_drag_does_not_raise(self, grid: PageGrid) -> None:
        """The in-progress highlight and insertion line must not crash mid-drag."""
        start = grid.visualItemRect(grid.item(1)).center()
        end = grid.visualItemRect(grid.item(4)).center()
        grid.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, start))
        grid.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, end))
        grid.repaint()
        grid.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, end, buttons=Qt.MouseButton.NoButton)
        )


class TestWhereADropLands:
    """The geometry rule behind a drag, checked at the places people actually aim."""

    def test_the_left_margin_means_the_very_front(self, grid: PageGrid) -> None:
        """Aiming left of page 1 must not fling the page to the end."""
        y = grid.visualItemRect(grid.item(0)).center().y()
        assert grid.gap_at(QPoint(5, y)) == 0

    def test_left_half_means_before_that_page(self, grid: PageGrid) -> None:
        rect = grid.visualItemRect(grid.item(2))
        point = QPoint(rect.left() + 10, rect.center().y())
        assert grid.gap_at(point) == 2

    def test_right_half_means_after_that_page(self, grid: PageGrid) -> None:
        rect = grid.visualItemRect(grid.item(2))
        point = QPoint(rect.right() - 10, rect.center().y())
        assert grid.gap_at(point) == 3

    def test_past_the_last_page_means_the_end(self, grid: PageGrid) -> None:
        rect = grid.visualItemRect(grid.item(5))
        point = QPoint(rect.right() - 10, rect.center().y())
        assert grid.gap_at(point) == 6

    def test_a_drop_below_everything_means_the_end(self, grid: PageGrid) -> None:
        assert grid.gap_at(QPoint(500, 690)) == 6


# --------------------------------------------------------------------------
# The window: wiring from the grid's signal to the session and back.
# --------------------------------------------------------------------------


class TestThroughTheWindow:
    """The window's response to `pages_moved`, independent of how it fired."""

    @pytest.fixture
    def window(self) -> Iterator[MainWindow]:
        made = MainWindow()
        yield made
        made.close()

    def test_a_drop_rearranges_the_grid(self, window: MainWindow, make_pdf: PageMaker) -> None:
        window._loaded(load(make_pdf(6)))
        window.grid.pages_moved.emit([2], 5)

        assert window.session is not None
        assert [p + 1 for p in window.session.order] == [1, 2, 4, 5, 3, 6]
        assert [p + 1 for p in window.grid.page_order()] == [1, 2, 4, 5, 3, 6]

    def test_tiles_are_renumbered_after_a_drop(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(6)))
        window.grid.pages_moved.emit([2], 5)
        labels = [window.grid.item(row).text() for row in range(window.grid.count())]
        assert labels == ["1", "2", "3", "4", "5", "6"]

    def test_the_dragged_page_stays_selected(self, window: MainWindow, make_pdf: PageMaker) -> None:
        window._loaded(load(make_pdf(6)))
        window.grid.pages_moved.emit([2], 5)
        selected = sorted(index.row() for index in window.grid.selectedIndexes())
        assert selected == [4]

    def test_a_drag_marks_the_document_unsaved(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(6)))
        assert window.session is not None
        assert not window.revert_button.isEnabled(), "nothing to revert yet"
        window.grid.pages_moved.emit([0], 6)
        assert window.session.modified
        assert window.revert_button.isEnabled(), "a drag is an unsaved change"

    def test_a_real_mouse_drag_reaches_the_session(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        """End to end: an actual mouse gesture on the real window's grid."""
        window._loaded(load(make_pdf(6)))
        window.show()
        _settle()

        start = window.grid.visualItemRect(window.grid.item(2)).center()
        target = window.grid.visualItemRect(window.grid.item(4))
        end = QPoint(target.right() - 5, target.center().y())
        _drag(window.grid, start, end)

        assert window.session is not None
        assert [p + 1 for p in window.session.order] == [1, 2, 4, 5, 3, 6]
