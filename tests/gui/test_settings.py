"""Tests for the desktop app's remembered preferences: dark mode, thumbnail
size, and the default compression level.

Three layers throughout: the pure logic (no Qt object involved at all), the
persisted value in `settings` (backed by a real `QSettings`, but pointed at a
throwaway file rather than the user's actual, shared one — the `store`
fixture below, and `tests/gui/conftest.py`'s autouse isolation for calls that
pass no `store` at all), and the dialog and window wiring that tie the two
together.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QDialog

from modpdf.gui import settings, theme
from modpdf.gui.session import load
from modpdf.gui.widgets import SectionLabel, SegmentedControl, ThemeToggle
from modpdf.gui.window import MainWindow
from tests.conftest import PageMaker
from tests.gui.conftest import wait_until

pytestmark = pytest.mark.usefixtures("qt_app")


@pytest.fixture
def store(tmp_path: Path) -> QSettings:
    """A `QSettings` backed by a file in `tmp_path` — never the real, shared,
    per-user settings location every actual launch of the app writes to."""
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


class TestTheme:
    def test_light_is_the_default(self) -> None:
        theme.set_mode(dark=False)
        assert not theme.is_dark()
        assert theme.BG == "#F4F5F7"

    def test_switching_to_dark_changes_the_palette(self) -> None:
        theme.set_mode(dark=True)
        try:
            assert theme.is_dark()
            assert theme.BG != "#F4F5F7"
            assert theme.INK != "#2E3742"
        finally:
            theme.set_mode(dark=False)  # leave it as every other test expects

    def test_slate_never_changes(self) -> None:
        """SLATE backs the Primary button and the tooltip in both modes —
        see the module docstring for why it is deliberately left out of the
        swap."""
        light_slate = theme.SLATE
        theme.set_mode(dark=True)
        try:
            assert theme.SLATE == light_slate
        finally:
            theme.set_mode(dark=False)

    def test_light_and_dark_define_the_same_names(self) -> None:
        """A palette missing a name would leave the other mode's value behind
        after a switch — silently half-themed rather than loudly broken."""
        assert set(theme._LIGHT) == set(theme._DARK)


class TestSettings:
    def test_defaults_to_light(self, store: QSettings) -> None:
        assert settings.dark_mode(store=store) is False

    def test_round_trips(self, store: QSettings) -> None:
        settings.set_dark_mode(True, store=store)
        assert settings.dark_mode(store=store) is True

    def test_does_not_touch_the_real_shared_settings(self, store: QSettings) -> None:
        """The whole reason `store` exists: prove a test can flip this
        without going anywhere near what a real launch of the app reads."""
        settings.set_dark_mode(True, store=store)
        assert settings.dark_mode() is False  # the real, default-backed store


class TestThumbnailSizeSetting:
    def test_defaults_to_medium(self, store: QSettings) -> None:
        assert settings.thumbnail_size(store=store) == "medium"

    def test_round_trips(self, store: QSettings) -> None:
        settings.set_thumbnail_size("large", store=store)
        assert settings.thumbnail_size(store=store) == "large"

    def test_an_unrecognised_stored_value_falls_back_to_medium(self, store: QSettings) -> None:
        """Hand-edited ini, or a future version's value this one doesn't know
        about — either way, a bad value should not raise or wedge the grid at
        an invalid size."""
        store.setValue("pages/thumbnail_size", "gigantic")
        assert settings.thumbnail_size(store=store) == "medium"


class TestDefaultCompressLevelSetting:
    def test_defaults_to_balanced(self, store: QSettings) -> None:
        assert settings.default_compress_level(store=store) == "balanced"

    def test_round_trips(self, store: QSettings) -> None:
        settings.set_default_compress_level("high", store=store)
        assert settings.default_compress_level(store=store) == "high"

    def test_an_unrecognised_stored_value_falls_back_to_the_default(self, store: QSettings) -> None:
        store.setValue("compress/default_level", "ludicrous")
        assert settings.default_compress_level(store=store) == "balanced"


class TestThemeToggle:
    """The slider itself, independent of the dialog it sits in."""

    def test_starts_on_light(self) -> None:
        assert not ThemeToggle().isChecked()

    def test_setting_true_reflects_in_is_checked(self) -> None:
        toggle = ThemeToggle()
        toggle.setChecked(True)
        assert toggle.isChecked()

    def test_a_click_flips_it(self) -> None:
        toggle = ThemeToggle()
        click = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(),
            QPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        toggle.mousePressEvent(click)
        assert toggle.isChecked()

    def test_toggled_fires_on_a_real_change(self) -> None:
        toggle = ThemeToggle()
        seen: list[bool] = []
        toggle.toggled.connect(seen.append)
        toggle.setChecked(True)
        assert seen == [True]

    def test_setting_the_same_value_again_does_not_refire(self) -> None:
        """A no-op `setChecked` shouldn't feed back into `set_dark_mode` a
        second time when the dialog wires this straight to it."""
        toggle = ThemeToggle()
        seen: list[bool] = []
        toggle.toggled.connect(seen.append)
        toggle.setChecked(False)  # already light
        assert seen == []


def _click_at(widget: object, x: int) -> None:
    """A left-click at horizontal position `x` within `widget`, for the
    segment-picking widgets whose `mousePressEvent` reads only the x
    coordinate."""
    click = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, 1),
        QPointF(x, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(click)  # type: ignore[attr-defined]


class TestSegmentedControl:
    """The three-or-more-option sibling of `ThemeToggle`, used in the
    Settings dialog for thumbnail size and the default compression level."""

    def test_needs_at_least_two_options(self) -> None:
        with pytest.raises(ValueError):
            SegmentedControl(["Only one"])

    def test_starts_on_the_first_option(self) -> None:
        assert SegmentedControl(["Small", "Medium", "Large"]).currentValue() == "Small"

    def test_set_current_value_changes_it(self) -> None:
        control = SegmentedControl(["Small", "Medium", "Large"])
        control.setCurrentValue("Large")
        assert control.currentValue() == "Large"

    def test_changed_fires_on_a_real_change(self) -> None:
        control = SegmentedControl(["Small", "Medium", "Large"])
        seen: list[str] = []
        control.changed.connect(seen.append)
        control.setCurrentValue("Medium")
        assert seen == ["Medium"]

    def test_setting_the_same_value_again_does_not_refire(self) -> None:
        control = SegmentedControl(["Small", "Medium", "Large"])
        seen: list[str] = []
        control.changed.connect(seen.append)
        control.setCurrentValue("Small")  # already there
        assert seen == []

    def test_a_click_picks_the_segment_under_it(self) -> None:
        control = SegmentedControl(["Small", "Medium", "Large"], segment_width=100)
        _click_at(control, 250)  # third segment: 200-300
        assert control.currentValue() == "Large"

    def test_refresh_theme_does_not_change_the_current_value(self) -> None:
        control = SegmentedControl(["Small", "Medium", "Large"])
        control.setCurrentValue("Large")
        control.refresh_theme()
        assert control.currentValue() == "Large"


class TestSettingsDialog:
    """`_show_settings` builds its toggle and dialog locally — nothing is
    kept on `window` to reach from outside — so each test replaces
    `ThemeToggle` for the one call, just long enough to capture the instance
    it creates, and replaces `QDialog.exec` so the modal never actually
    blocks the test.
    """

    @pytest.fixture
    def window(self) -> Iterator[MainWindow]:
        made = MainWindow()
        yield made
        made.close()

    def _spy_on_the_toggle(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, ThemeToggle]:
        captured: dict[str, ThemeToggle] = {}

        def spying_toggle() -> ThemeToggle:
            toggle = ThemeToggle()
            captured["toggle"] = toggle
            return toggle

        monkeypatch.setattr("modpdf.gui.window.ThemeToggle", spying_toggle)
        monkeypatch.setattr(QDialog, "exec", lambda self: None)
        return captured

    def _spy_on_the_segmented_controls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> list[SegmentedControl]:
        """Both new settings use the same `SegmentedControl` class, built in
        this order: thumbnail size first, then compression level — so
        `created[0]` and `created[1]` below name them by position rather
        than by a distinguishing constructor argument."""
        created: list[SegmentedControl] = []

        class RecordingControl(SegmentedControl):
            def __init__(self, options: list[str], *, segment_width: int = 96) -> None:
                super().__init__(options, segment_width=segment_width)
                created.append(self)

        monkeypatch.setattr("modpdf.gui.window.SegmentedControl", RecordingControl)
        monkeypatch.setattr(QDialog, "exec", lambda self: None)
        return created

    def test_the_toggle_reflects_the_stored_value(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "dark_mode", lambda: True)
        captured = self._spy_on_the_toggle(monkeypatch)

        window._show_settings()

        assert captured["toggle"].isChecked()

    def test_flipping_the_toggle_persists_the_choice(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "dark_mode", lambda: False)
        seen: list[bool] = []
        monkeypatch.setattr(settings, "set_dark_mode", lambda value: seen.append(value))
        # The live re-theme is exercised on its own in TestApplyTheme; stub it
        # out here so this test is only about persistence.
        monkeypatch.setattr(window, "_apply_theme", lambda *, dark: None)
        captured = self._spy_on_the_toggle(monkeypatch)

        window._show_settings()
        captured["toggle"].setChecked(True)

        assert seen == [True]

    def test_flipping_the_toggle_re_themes_the_window_live(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of this session's change: no more "restart to
        apply" — flipping the slider must reach the open window immediately."""
        monkeypatch.setattr(settings, "dark_mode", lambda: False)
        monkeypatch.setattr(settings, "set_dark_mode", lambda value: None)
        seen: list[bool] = []
        monkeypatch.setattr(window, "_apply_theme", lambda *, dark: seen.append(dark))
        captured = self._spy_on_the_toggle(monkeypatch)

        window._show_settings()
        captured["toggle"].setChecked(True)

        assert seen == [True]

    def test_the_sections_appear_thumbnail_then_compression_then_appearance_last(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialogs: list[QDialog] = []
        monkeypatch.setattr(QDialog, "exec", lambda self: dialogs.append(self))

        window._show_settings()

        layout = dialogs[0].layout()
        assert layout is not None
        headings = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, SectionLabel):
                headings.append(widget.text())
        assert headings == ["THUMBNAIL SIZE", "DEFAULT COMPRESSION LEVEL", "APPEARANCE"]

    def test_the_thumbnail_control_reflects_the_stored_value(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "thumbnail_size", lambda: "large")
        created = self._spy_on_the_segmented_controls(monkeypatch)

        window._show_settings()

        assert created[0].currentValue() == "Large"

    def test_the_compress_control_reflects_the_stored_value(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "default_compress_level", lambda: "high")
        created = self._spy_on_the_segmented_controls(monkeypatch)

        window._show_settings()

        assert created[1].currentValue() == "Maximum"

    def test_changing_the_thumbnail_control_applies_live(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "thumbnail_size", lambda: "medium")
        seen: list[str] = []
        monkeypatch.setattr(window, "_set_thumbnail_size", lambda size: seen.append(size))
        created = self._spy_on_the_segmented_controls(monkeypatch)

        window._show_settings()
        created[0].setCurrentValue("Small")

        assert seen == ["small"]

    def test_changing_the_compress_control_applies_live(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "default_compress_level", lambda: "balanced")
        seen: list[str] = []
        monkeypatch.setattr(window, "_set_default_compress_level", lambda level: seen.append(level))
        created = self._spy_on_the_segmented_controls(monkeypatch)

        window._show_settings()
        created[1].setCurrentValue("Best")

        assert seen == ["low"]


class TestApplyTheme:
    """`_apply_theme` itself: it mutates the process-wide palette, so every
    test resets it to light afterwards — the same discipline `TestTheme`
    uses above, for the same reason."""

    @pytest.fixture
    def window(self) -> Iterator[MainWindow]:
        made = MainWindow()
        yield made
        made.close()
        theme.set_mode(dark=False)  # leave global state as every other test expects

    def test_switches_the_palette(self, window: MainWindow) -> None:
        window._apply_theme(dark=True)
        assert theme.is_dark()
        assert window.styleSheet() == theme.stylesheet()

    def test_switching_back_restores_light(self, window: MainWindow) -> None:
        window._apply_theme(dark=True)
        window._apply_theme(dark=False)
        assert not theme.is_dark()

    def test_rebuilds_the_central_widget_rather_than_leaving_it_stale(
        self, window: MainWindow
    ) -> None:
        header_before = window.title_label
        window._apply_theme(dark=True)
        assert window.title_label is not header_before

    def test_an_open_document_survives_the_rebuild(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(5, name="report.pdf")))
        window._apply_theme(dark=True)
        assert window.session is not None
        assert window.session.path.name == "report.pdf"
        assert window.stack.currentIndex() == 1
        assert window.grid.count() == 5

    def test_the_page_selection_survives_the_rebuild(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(5, name="report.pdf")))
        window.grid.item(1).setSelected(True)
        window.grid.item(3).setSelected(True)

        window._apply_theme(dark=True)

        assert window._selected_positions() == [1, 3]

    def test_the_active_panel_survives_the_rebuild(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(5, name="report.pdf")))
        window._show_panel("split")

        window._apply_theme(dark=True)

        assert window.panels.currentIndex() == window.panel_index["split"]
        assert window.tool_buttons["split"].isChecked()

    def test_the_split_ranges_survive_the_rebuild(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(8, name="report.pdf")))
        window._range_rows[0].start.setValue(2)
        window._range_rows[0].end.setValue(4)
        window._add_range_row(5, 8)

        window._apply_theme(dark=True)

        assert [row.value() for row in window._range_rows] == [(2, 4), (5, 8)]

    def test_the_compress_choice_survives_the_rebuild(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        window._loaded(load(make_pdf(3, name="report.pdf")))
        window.compress_lossless_radio.setChecked(True)

        window._apply_theme(dark=True)

        assert window.compress_lossless_radio.isChecked()
        assert not window.compress_visual_radio.isChecked()


class TestThumbnailSizeApplication:
    """`_set_thumbnail_size` itself, independent of the Settings dialog."""

    @pytest.fixture
    def window(self) -> Iterator[MainWindow]:
        made = MainWindow()
        yield made
        made.close()

    def test_persists_the_choice(self, window: MainWindow) -> None:
        window._set_thumbnail_size("large")
        assert settings.thumbnail_size() == "large"

    def test_resizes_the_grid_immediately(self, window: MainWindow) -> None:
        window._set_thumbnail_size("large")
        assert window.grid.iconSize().width() == 232

    def test_a_no_op_size_leaves_the_grid_alone(self, window: MainWindow) -> None:
        """Already "medium" (the default) — nothing to clear or re-render."""
        before = window.grid.iconSize()
        window._set_thumbnail_size("medium")
        assert window.grid.iconSize() == before

    def test_no_document_open_still_resizes_the_grid(self, window: MainWindow) -> None:
        window._set_thumbnail_size("small")
        assert window.grid.iconSize().width() == 112
        assert window.session is None

    def test_an_open_documents_stale_thumbnails_are_not_kept(
        self, window: MainWindow, make_pdf: PageMaker
    ) -> None:
        """A stretched 112px placeholder standing in for a 232px tile would
        look visibly soft next to its neighbours — so a size change must
        clear what is cached and let it re-render at the new width, not
        just resize the grid around the old pixmaps."""
        window._loaded(load(make_pdf(3, name="report.pdf")))
        stale = QPixmap(10, 10)
        window._thumbnails[0] = stale  # pretend a thumbnail at the old size already rendered

        window._set_thumbnail_size("large")
        wait_until(lambda: 0 in window._thumbnails)

        assert window._thumbnails[0] is not stale
        assert window._thumbnails[0].width() == 232


class TestDefaultCompressLevelApplication:
    @pytest.fixture
    def window(self, make_pdf: PageMaker) -> Iterator[MainWindow]:
        made = MainWindow()
        made._loaded(load(make_pdf(3, name="report.pdf")))
        made._show_panel("compress")
        yield made
        made.close()

    def test_the_panel_starts_on_the_persisted_default(self, make_pdf: PageMaker) -> None:
        settings.set_default_compress_level("high")
        try:
            made = MainWindow()
            made._loaded(load(make_pdf(3, name="report.pdf")))
            assert made.compress_maximum_radio.isChecked()
            made.close()
        finally:
            settings.set_default_compress_level("balanced")  # leave the default as found

    def test_picking_a_level_in_the_panel_persists_it(self, window: MainWindow) -> None:
        window.compress_maximum_radio.setChecked(True)
        assert settings.default_compress_level() == "high"

    def test_set_default_compress_level_syncs_an_open_panels_radio(
        self, window: MainWindow
    ) -> None:
        window._set_default_compress_level("high")
        assert window.compress_maximum_radio.isChecked()
        assert not window.compress_balanced_radio.isChecked()

    def test_set_default_compress_level_persists_the_choice(self, window: MainWindow) -> None:
        window._set_default_compress_level("low")
        assert settings.default_compress_level() == "low"
