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
from modpdf.ops.compress import CompressReport, ImageSummary, Mode
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
    level = window.compress_level_choice()
    result = tasks.compress_file(
        window.session.path,
        destination,
        mode=mode,
        level=level,
        password=window.session.password,
        overwrite=True,
    )
    window._compressed(result, level)


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

    def test_the_default_level_matches_the_documented_default(self, window: MainWindow) -> None:
        from modpdf.ops.compress import DEFAULT_LEVEL

        assert window.compress_level_choice() == DEFAULT_LEVEL
        assert window.compress_balanced_radio.isChecked()

    def test_the_three_levels_are_mutually_exclusive(self, window: MainWindow) -> None:
        window.compress_maximum_radio.setChecked(True)
        assert not window.compress_quality_radio.isChecked()
        assert not window.compress_balanced_radio.isChecked()
        assert window.compress_level_choice() == "high"

        window.compress_quality_radio.setChecked(True)
        assert not window.compress_maximum_radio.isChecked()
        assert window.compress_level_choice() == "low"

    def test_the_level_picker_is_disabled_in_lossless_mode(self, window: MainWindow) -> None:
        window.compress_lossless_radio.setChecked(True)
        assert not window.compress_level_container.isEnabled()

        window.compress_visual_radio.setChecked(True)
        assert window.compress_level_container.isEnabled()


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

    def test_selecting_maximum_compression_reaches_the_task_layer(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        """Proves the checked radio, not a hardcoded default, is what gets
        used: "Maximum compression" must produce a *different* result than
        the panel's own default ("Balanced") on the same source document.

        Not necessarily a smaller one — this window's fixture document is a
        plain photo with no vector page to flatten, which is a real, accepted
        case where "high" ends up larger than "balanced" (see
        `test_high_can_end_up_larger_than_balanced_on_a_plain_photo` in
        test_compress.py). What this test is actually proving is narrower:
        that toggling the radio changes which settings reach `tasks.py`
        at all, not which tier wins on this particular document.
        """
        balanced_out = tmp_path / "balanced.pdf"
        run_compress(window, balanced_out)
        balanced_size = balanced_out.stat().st_size

        window.compress_maximum_radio.setChecked(True)
        maximum_out = tmp_path / "maximum.pdf"
        run_compress(window, maximum_out)

        assert maximum_out.stat().st_size != balanced_size

    def test_maximum_compression_says_quality_was_traded_away(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        window.compress_maximum_radio.setChecked(True)
        run_compress(window, tmp_path / "out.pdf")
        assert "reduced on purpose" in window.compress_result.text()

    def test_balanced_does_not_say_that(self, window: MainWindow, tmp_path: Path) -> None:
        run_compress(window, tmp_path / "out.pdf")
        assert "reduced on purpose" not in window.compress_result.text()


class TestTheFallbackIsShownClearly:
    """The compression itself falling back to lossless is already covered
    thoroughly in `tests/unit/test_compress.py`; what belongs here is only
    that the window renders `report.fell_back` correctly, which does not
    need a real compression that happens to trip the gate — constructing the
    report directly is simpler and does not depend on tuning a fixture."""

    def test_a_fallback_report_is_shown_as_such(self, window: MainWindow, tmp_path: Path) -> None:
        out = tmp_path / "out.pdf"
        out.write_bytes(b"stand-in for a real write, never read back")
        report = CompressReport(
            before_bytes=1_000_000,
            after_bytes=800_000,
            mode_used="lossless",
            images=ImageSummary(),
            fell_back=True,
            fallback_reason="page 1: 40.0% of pixels changed visibly, above the 35% limit",
        )
        window._compressed((out, report))
        assert "fell back to lossless" in window.compress_result.text()


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
