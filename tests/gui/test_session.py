"""Tests for the window's editing state.

No Qt here: a session is plain data plus the rules for changing it, which is
deliberate — the interesting logic should be testable without a display.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modpdf.gui.session import Session, load
from tests.conftest import PageMaker, page_markers


@pytest.fixture
def session(make_pdf: PageMaker) -> Session:
    return load(make_pdf(6, name="doc.pdf"))


class TestLoading:
    def test_starts_as_the_file_on_disk(self, session: Session) -> None:
        assert session.source_pages == 6
        assert session.order == [0, 1, 2, 3, 4, 5]
        assert session.modified is False

    def test_inspects_on_open(self, session: Session) -> None:
        """So the window can show what is in the file without being asked."""
        assert session.inspection.page_count == 6
        assert session.inspection.size_bytes > 0


class TestEditing:
    def test_removing_pages(self, session: Session) -> None:
        session.remove([0, 5])
        assert session.order == [1, 2, 3, 4]
        assert session.modified is True
        assert session.dropped == 2

    def test_removing_every_page_is_refused(self, session: Session) -> None:
        with pytest.raises(ValueError, match="at least one page"):
            session.remove(range(6))

    def test_duplicating_inserts_after_the_original(self, session: Session) -> None:
        session.duplicate([1])
        assert session.order == [0, 1, 1, 2, 3, 4, 5]

    def test_reordering(self, session: Session) -> None:
        session.reorder([5, 4, 3, 2, 1, 0])
        assert session.order == [5, 4, 3, 2, 1, 0]

    def test_a_reorder_may_not_invent_or_lose_pages(self, session: Session) -> None:
        with pytest.raises(ValueError, match="same pages"):
            session.reorder([0, 1, 2])

    def test_revert_goes_back_to_the_file(self, session: Session) -> None:
        session.remove([0])
        session.duplicate([0])
        session.revert()
        assert session.order == [0, 1, 2, 3, 4, 5]
        assert session.modified is False


class TestSaving:
    def test_writes_the_pending_order(self, session: Session, tmp_path: Path) -> None:
        session.reorder([5, 0, 1, 2, 3, 4])
        out = session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [6, 1, 2, 3, 4, 5]

    def test_deleting_then_saving_drops_those_pages(self, session: Session, tmp_path: Path) -> None:
        session.remove([0, 1])
        out = session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [3, 4, 5, 6]

    def test_duplicating_then_saving_repeats_the_page(
        self, session: Session, tmp_path: Path
    ) -> None:
        session.remove([2, 3, 4, 5])
        session.duplicate([0])
        out = session.save_to(tmp_path / "out.pdf")
        assert page_markers(out) == [1, 1, 2]

    def test_the_source_file_is_never_touched(self, session: Session, tmp_path: Path) -> None:
        before = session.path.read_bytes()
        session.remove([0])
        session.save_to(tmp_path / "out.pdf")
        assert session.path.read_bytes() == before
