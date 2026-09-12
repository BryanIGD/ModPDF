"""Tests for building a workspace out of more than one PDF via the Open button.

There is a single Open button. With nothing loaded, it opens a file, same as
always; with a document already open, choosing another file through it adds
that file's pages onto the end instead of replacing the workspace. Dropping
one file behaves the same way; dropping several at once is the separate,
existing "merge to a new file" behaviour, untouched here.

`tasks.append_document` has its own thorough coverage in
`tests/unit/test_tasks.py`; these tests are about the window's wiring — that
choosing a file while one is already open reaches the task layer with the
right arguments, that pending edits on the document already open survive it,
and that the combined result becomes the new workspace rather than a one-off
file written to disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from modpdf import tasks
from modpdf.gui.session import load
from modpdf.gui.window import MainWindow
from tests.conftest import PageMaker, page_markers

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def window() -> Iterator[MainWindow]:
    made = MainWindow()
    yield made
    made.close()


def run_add(window: MainWindow, path: Path, password: str | None = None) -> None:
    """The same work `add_path` does, synchronously — the worker-thread
    indirection is `workers.run`'s own concern, exercised separately below."""
    session = window.session
    assert session is not None
    destination = window._next_workspace_path(session.path.stem, path.stem)
    written, _ = tasks.append_document(
        session.path,
        session.order,
        path,
        destination,
        password=session.password,
        addition_password=password,
        overwrite=True,
    )
    window._loaded(load(written))


class TestThereIsOnlyOneButton:
    def test_no_separate_add_button_exists(self, window: MainWindow) -> None:
        assert not hasattr(window, "add_button")

    def test_open_is_always_enabled_even_with_nothing_open(self, window: MainWindow) -> None:
        assert window.session is None
        assert window.open_button.isEnabled()

    def test_choosing_a_file_adds_it_when_a_document_is_already_open(
        self, window: MainWindow, make_pdf: PageMaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window._loaded(load(make_pdf(1, name="first.pdf")))
        chosen = make_pdf(1, name="second.pdf")

        def fake_dialog(*args: Any, **kwargs: Any) -> tuple[str, str]:
            return (str(chosen), "")

        monkeypatch.setattr("modpdf.gui.window.QFileDialog.getOpenFileName", fake_dialog)
        captured: list[Path] = []

        def fake_add_path(path: Path, password: str | None = None) -> None:
            captured.append(path)

        monkeypatch.setattr(window, "add_path", fake_add_path)

        window.choose_file()
        assert captured == [chosen]

    def test_the_dialog_title_reflects_which_it_will_do(
        self, window: MainWindow, make_pdf: PageMaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        titles: list[str] = []

        def fake_dialog(_parent: object, title: str, *a: object, **k: object) -> tuple[str, str]:
            titles.append(title)
            return ("", "")

        monkeypatch.setattr("modpdf.gui.window.QFileDialog.getOpenFileName", fake_dialog)

        window.choose_file()
        assert titles == ["Open a PDF"]

        window._loaded(load(make_pdf(1, name="first.pdf")))
        window.choose_file()
        assert titles == ["Open a PDF", "Add a PDF"]


class TestAddingWithNothingOpenYet:
    def test_it_behaves_like_open(
        self, window: MainWindow, make_pdf: PageMaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[Path, str | None]] = []
        monkeypatch.setattr(
            window, "open_path", lambda path, password=None: calls.append((path, password))
        )
        source = make_pdf(2, name="first.pdf")
        window.add_path(source)
        assert calls == [(source, None)]


class TestDispatching:
    def test_add_reaches_the_task_layer_with_the_right_arguments(
        self, window: MainWindow, make_pdf: PageMaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window._loaded(load(make_pdf(2, name="first.pdf")))
        session = window.session
        assert session is not None

        captured: dict[str, Any] = {}

        def fake_run(work: Any, *args: Any, **kwargs: Any) -> None:
            captured["work"] = work
            captured["args"] = args
            captured["kwargs"] = kwargs

        monkeypatch.setattr("modpdf.gui.workers.run", fake_run)
        addition = make_pdf(1, name="second.pdf")
        window.add_path(addition)

        assert captured["work"] is tasks.append_document
        base_path, base_order, addition_path, destination = captured["args"]
        assert base_path == session.path
        assert base_order == session.order
        assert addition_path == addition
        assert destination.name == "first+second.pdf"
        assert captured["kwargs"]["password"] == session.password
        assert captured["kwargs"]["overwrite"] is True


class TestAddingToAnOpenDocument:
    def test_pages_from_both_files_are_present_in_order(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(2, name="first.pdf")))
        run_add(window, make_pdf(3, name="second.pdf"))

        session = window.session
        assert session is not None
        assert session.pages == 5
        assert page_markers(session.path) == [1, 2, 1, 2, 3]

    def test_pending_reordering_on_the_base_survives_the_add(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(3, name="first.pdf")))
        session = window.session
        assert session is not None
        session.reorder([2, 0, 1])  # as if dragged to read 3, 1, 2
        run_add(window, make_pdf(1, name="second.pdf"))

        assert page_markers(window.session.path) == [3, 1, 2, 1]  # type: ignore[union-attr]

    def test_pending_deletion_on_the_base_survives_the_add(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(3, name="first.pdf")))
        window.grid.item(1).setSelected(True)  # page 2
        window.delete_selected()
        run_add(window, make_pdf(1, name="second.pdf"))

        assert page_markers(window.session.path) == [1, 3, 1]  # type: ignore[union-attr]

    def test_the_workspace_gets_a_readable_combined_name(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(2, name="deposition.pdf")))
        run_add(window, make_pdf(1, name="appendix.pdf"))
        session = window.session
        assert session is not None
        assert session.path.name == "deposition+appendix.pdf"

    def test_adding_a_third_file_keeps_building_on_the_combined_name(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(1, name="a.pdf")))
        run_add(window, make_pdf(1, name="b.pdf"))
        run_add(window, make_pdf(1, name="c.pdf"))
        session = window.session
        assert session is not None
        assert session.path.name == "a+b+c.pdf"
        assert page_markers(session.path) == [1, 1, 1]

    def test_the_combined_document_has_no_pending_edits_of_its_own(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        """After Add, the combined file is the new baseline — Revert on it
        should be a no-op, not a way to lose the file you just added."""
        window._loaded(load(make_pdf(2, name="first.pdf")))
        run_add(window, make_pdf(1, name="second.pdf"))
        session = window.session
        assert session is not None
        assert not session.modified

    def test_the_grid_shows_every_page_from_both_files(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(2, name="first.pdf")))
        run_add(window, make_pdf(3, name="second.pdf"))
        assert window.grid.count() == 5
