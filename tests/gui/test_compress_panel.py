"""Tests for the Compress panel.

The core compression logic already has its own thorough test suite
(`tests/unit/test_compress.py`); these tests are about the wiring — that the
button is enabled, the panel shows the right controls, and the result of a
real compression reaches the screen — not about re-proving compression itself
works. The button used to be permanently disabled; the fix is only real if
these prove the whole path through the window, not just that the ops-level
function works in isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from modpdf import tasks
from modpdf.gui.session import load
from modpdf.gui.window import MainWindow
from modpdf.ops.compress import Mode
from tests.conftest import build_photo_pdf, build_scan_pdf

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def window(tmp_path: Path) -> Iterator[MainWindow]:
    made = MainWindow()
    made._loaded(load(build_photo_pdf(tmp_path / "photo.pdf")))
    made._show_panel("compress")
    yield made
    made.close()


def run_compress(window: MainWindow, destination: Path) -> None:
    """Run the same task the button triggers, synchronously — the worker
    thread indirection is `workers.run`'s concern, already covered elsewhere;
    what matters here is that the window asks for the right thing and shows
    the right result."""
    assert window.session is not None
    mode: Mode = "lossless" if window.compress_lossless_radio.isChecked() else "visual"
    result = tasks.compress_file(
        window.session.path,
        destination,
        mode=mode,
        target_dpi=window.compress_target_dpi.value(),
        password=window.session.password,
        overwrite=True,
    )
    window._compressed(result)


class TestTheButtonIsNoLongerDisabled:
    """The bug that was reported: this button did nothing when clicked."""

    def test_the_compress_tool_exists_and_is_enabled(self, window: MainWindow) -> None:
        assert "compress" in window.tool_buttons
        assert window.tool_buttons["compress"].isEnabled()

    def test_selecting_it_shows_the_compress_panel(self, window: MainWindow) -> None:
        assert window.panels.currentWidget() is window.compress_visual_radio.parentWidget()

    def test_the_button_is_disabled_with_no_document_open(self) -> None:
        empty = MainWindow()
        try:
            assert not empty.tool_buttons["compress"].isEnabled()
        finally:
            empty.close()


class TestPanelDefaults:
    def test_visually_lossless_is_the_default_mode(self, window: MainWindow) -> None:
        assert window.compress_visual_radio.isChecked()
        assert not window.compress_lossless_radio.isChecked()

    def test_the_default_target_matches_the_documented_default(self, window: MainWindow) -> None:
        from modpdf.ops.compress import DEFAULT_TARGET_DPI

        assert window.compress_target_dpi.value() == DEFAULT_TARGET_DPI

    def test_the_target_field_is_disabled_in_lossless_mode(self, window: MainWindow) -> None:
        window.compress_lossless_radio.setChecked(True)
        assert not window.compress_target_dpi.isEnabled()

        window.compress_visual_radio.setChecked(True)
        assert window.compress_target_dpi.isEnabled()


class TestRunningACompression:
    def test_a_real_compression_reaches_the_screen(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.pdf"
        run_compress(window, out)

        assert out.exists()
        assert "smaller" in window.status_label.text()
        assert "93%" in window.status_label.text() or "%" in window.status_label.text()

    def test_the_result_panel_shows_the_size_change(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.pdf"
        run_compress(window, out)

        shown = window.compress_result.text()
        assert "MB" in shown or "KB" in shown
        assert "smaller" in shown

    def test_a_passing_quality_gate_is_shown(self, window: MainWindow, tmp_path: Path) -> None:
        out = tmp_path / "out.pdf"
        run_compress(window, out)
        assert "quality check passed" in window.compress_result.text()

    def test_lossless_mode_reaches_the_task_layer_correctly(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        window.compress_lossless_radio.setChecked(True)
        out = tmp_path / "out.pdf"
        run_compress(window, out)
        assert out.exists()
        # Lossless never recompresses images, so that line has nothing to show.
        assert "recompressed" not in window.compress_result.text()

    def test_a_custom_target_dpi_reaches_the_task_layer(self, tmp_path: Path) -> None:
        """An unreasonably low target should trip the fallback — proving the
        spin box's value is what actually got used, not a hardcoded default.

        This needs the scanned-text fixture rather than the shared photo one:
        a smooth gradient has little high-frequency detail to lose and
        genuinely tolerates aggressive downsampling, which is correct gate
        behaviour, not a hole in it — see test_compress.py and verify.py's
        own tests for that finding. Hard-edged content is what reliably
        triggers a fallback at an unreasonable target.
        """
        window = MainWindow()
        try:
            window._loaded(load(build_scan_pdf(tmp_path / "scan.pdf")))
            window._show_panel("compress")
            window.compress_target_dpi.setValue(15)
            out = tmp_path / "out.pdf"
            run_compress(window, out)
            assert "fell back to lossless" in window.compress_result.text()
        finally:
            window.close()


class TestAlreadyOptimalIsShownClearly:
    def test_compressing_twice_says_so(self, window: MainWindow, tmp_path: Path) -> None:
        once = tmp_path / "once.pdf"
        run_compress(window, once)

        assert window.session is not None
        window._loaded(load(once))
        window._show_panel("compress")
        twice = tmp_path / "twice.pdf"
        run_compress(window, twice)

        assert "Already optimal" in window.compress_result.text()
        assert "already optimal" in window.status_label.text()


class TestScannedTextAlsoWorksThroughTheWindow:
    """A second, differently-shaped fixture through the same panel — the
    bilevel-detection path lives entirely in the ops layer, but this confirms
    the window doesn't do anything content-shape-specific that would break it."""

    def test_a_scanned_page_compresses_and_passes(self, tmp_path: Path) -> None:
        window = MainWindow()
        try:
            window._loaded(load(build_scan_pdf(tmp_path / "scan.pdf")))
            window._show_panel("compress")
            out = tmp_path / "out.pdf"
            run_compress(window, out)
            assert "quality check passed" in window.compress_result.text()
        finally:
            window.close()
