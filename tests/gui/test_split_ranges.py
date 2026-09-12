"""Tests for splitting by arbitrary page ranges.

Two layers again: `chunk_positions`/`positions_to_groups` are the pure rule for
turning a range list into groups of source page indices, checked without a
window; the panel tests below drive the actual radio buttons and range rows,
because a widget wired to the wrong signal, or a panel that never becomes the
active one in its stack, would pass the pure-logic tests while doing nothing
on screen — exactly the kind of gap that let the drag issue through earlier.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from modpdf.gui.session import chunk_positions, load, positions_to_groups
from modpdf.gui.window import MainWindow
from tests.conftest import PageMaker, page_markers

pytestmark = pytest.mark.usefixtures("qt_app")


# --------------------------------------------------------------------------
# The pure rule: ranges and chunks against the current order.
# --------------------------------------------------------------------------


class TestChunkPositions:
    def test_splits_into_even_runs(self) -> None:
        assert chunk_positions(list(range(8)), 3) == [[0, 1, 2], [3, 4, 5], [6, 7]]

    def test_follows_the_current_order_not_the_source(self) -> None:
        """Page 8 dragged to the front must appear in the first chunk."""
        reordered = [7, 0, 1, 2, 3, 4, 5, 6]
        assert chunk_positions(reordered, 3) == [[7, 0, 1], [2, 3, 4], [5, 6]]


class TestPositionsToGroups:
    def test_basic_ranges(self) -> None:
        order = list(range(8))
        assert positions_to_groups(order, [(1, 3), (5, 5), (6, 8)]) == [
            [0, 1, 2],
            [4],
            [5, 6, 7],
        ]

    def test_follows_the_current_order_not_the_source(self) -> None:
        """ "Pages 1 to 3" after a drag means the first three tiles now shown."""
        reordered = [7, 0, 1, 2, 3, 4, 5, 6]
        assert positions_to_groups(reordered, [(1, 3)]) == [[7, 0, 1]]

    def test_a_reversed_pair_is_swapped_not_refused(self) -> None:
        """Two spin boxes carry no ambiguity about which end is which."""
        assert positions_to_groups(list(range(8)), [(5, 2)]) == [[1, 2, 3, 4]]

    def test_an_end_past_the_document_is_clamped(self) -> None:
        assert positions_to_groups(list(range(8)), [(6, 99)]) == [[5, 6, 7]]

    def test_a_range_entirely_outside_the_document_is_dropped(self) -> None:
        assert positions_to_groups(list(range(8)), [(20, 30)]) == []

    def test_several_ranges_may_overlap(self) -> None:
        """Overlapping ranges are legal: the same page can appear in two files."""
        assert positions_to_groups(list(range(5)), [(1, 3), (2, 4)]) == [
            [0, 1, 2],
            [1, 2, 3],
        ]

    def test_a_single_page_range(self) -> None:
        assert positions_to_groups(list(range(5)), [(3, 3)]) == [[2]]


# --------------------------------------------------------------------------
# The panel: real widgets, switched to and driven directly.
# --------------------------------------------------------------------------


@pytest.fixture
def window(make_pdf: PageMaker) -> Iterator[MainWindow]:
    made = MainWindow()
    made._loaded(load(make_pdf(8, name="report.pdf")))
    made._show_panel("split")  # the panel must be the active one to mean anything
    yield made
    made.close()


class TestTheSplitPanel:
    def test_every_n_pages_is_the_default_mode(self, window: MainWindow) -> None:
        assert window.split_every_radio.isChecked()
        assert not window.ranges_container.isVisibleTo(window)

    def test_switching_to_ranges_shows_the_editor(self, window: MainWindow) -> None:
        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        assert window.ranges_container.isVisibleTo(window)
        assert window.add_range_button.isVisibleTo(window)
        assert not window.split_size.isEnabled()

    def test_switching_to_ranges_seeds_one_row(self, window: MainWindow) -> None:
        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        assert len(window._range_rows) == 1
        assert window._range_rows[0].value() == (1, 1)

    def test_switching_back_hides_the_editor_and_reenables_every_n(
        self, window: MainWindow
    ) -> None:
        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        window.split_every_radio.setChecked(True)
        window._split_mode_changed()
        assert not window.ranges_container.isVisibleTo(window)
        assert window.split_size.isEnabled()


class TestBuildingRanges:
    def _enter_ranges_mode(self, window: MainWindow) -> None:
        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()

    def test_the_example_from_the_request(self, window: MainWindow) -> None:
        """Range 1: page 1. Range 2: pages 2 to 3. Exactly the request's example."""
        self._enter_ranges_mode(window)
        window._range_rows[0].start.setValue(1)
        window._range_rows[0].end.setValue(1)
        window._add_range_row()
        window._range_rows[1].start.setValue(2)
        window._range_rows[1].end.setValue(3)

        assert [row.value() for row in window._range_rows] == [(1, 1), (2, 3)]
        assert window._current_split_groups() == [[0], [1, 2]]

    def test_add_range_defaults_to_starting_after_the_previous_one(
        self, window: MainWindow
    ) -> None:
        self._enter_ranges_mode(window)
        window._range_rows[0].start.setValue(2)
        window._range_rows[0].end.setValue(4)
        window._add_range_row()
        assert window._range_rows[1].value() == (5, 5)

    def test_removing_a_row(self, window: MainWindow) -> None:
        self._enter_ranges_mode(window)
        window._add_range_row()
        window._add_range_row()
        assert len(window._range_rows) == 3

        middle = window._range_rows[1]
        window._remove_range_row(middle)
        assert len(window._range_rows) == 2
        assert middle not in window._range_rows

    def test_the_last_row_cannot_be_removed(self, window: MainWindow) -> None:
        """There must always be something to split."""
        self._enter_ranges_mode(window)
        assert len(window._range_rows) == 1
        window._remove_range_row(window._range_rows[0])
        assert len(window._range_rows) == 1

    def test_row_maximums_track_the_document(self, window: MainWindow) -> None:
        self._enter_ranges_mode(window)
        assert window._range_rows[0].end.maximum() == 8

        window.grid.item(0).setSelected(True)
        window.delete_selected()  # 8 pages -> 7
        assert window._range_rows[0].end.maximum() == 7

    def test_a_stale_end_value_re_clamps_after_a_deletion(self, window: MainWindow) -> None:
        """Not just the bound: a row already set to 8 must not still say so on 7 pages."""
        self._enter_ranges_mode(window)
        window._range_rows[0].end.setValue(8)

        window.grid.item(0).setSelected(True)
        window.delete_selected()

        assert window._range_rows[0].end.value() == 7


class TestSplittingReflectsTheCurrentOrder:
    """Split must follow what the grid shows, including pending drags."""

    def test_ranges_are_counted_against_the_edited_order(self, window: MainWindow) -> None:
        assert window.session is not None
        window.session.move([7], 0)  # drag the last page to the front
        window._populate_grid()

        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        window._range_rows[0].start.setValue(1)
        window._range_rows[0].end.setValue(1)

        assert window._current_split_groups() == [[7]], "range 1 must now mean the dragged page"

    def test_every_n_is_also_counted_against_the_edited_order(self, window: MainWindow) -> None:
        assert window.session is not None
        window.session.move([7], 0)
        window._populate_grid()
        window.split_size.setValue(3)
        assert window._current_split_groups()[0] == [7, 0, 1]


class TestWritingToDisk:
    def test_the_example_from_the_request_writes_correct_files(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        window._range_rows[0].start.setValue(4)
        window._range_rows[0].end.setValue(4)
        window._add_range_row()
        window._range_rows[1].start.setValue(5)
        window._range_rows[1].end.setValue(6)

        assert window.session is not None
        from modpdf import tasks
        from modpdf.ops.split import plan_pieces

        groups = window._current_split_groups()
        pieces = plan_pieces(window.session.path.stem, groups)
        written = tasks.split_document(window.session.path, pieces, tmp_path)

        assert len(written) == 2
        by_name = {path.name: page_markers(path) for path in written}
        assert sorted(by_name.values()) == [[4], [5, 6]]

    def test_no_groups_is_refused_cleanly_rather_than_crashing(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A defensive check: the range spin boxes cannot themselves produce an
        empty group (they clamp to the document's real page range), but
        `split_document` must still handle it gracefully if it ever happens —
        rather than opening a file dialog for nothing or raising.
        """
        from PySide6.QtWidgets import QMessageBox

        window.split_ranges_radio.setChecked(True)
        window._split_mode_changed()
        window._range_rows.clear()  # force the otherwise-unreachable empty case

        shown: list[object] = []

        def fake_information(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
            shown.append(args)
            return QMessageBox.StandardButton.Ok

        monkeypatch.setattr(QMessageBox, "information", fake_information)
        window.split_document()
        assert shown, "the user must be told there is nothing to split"
