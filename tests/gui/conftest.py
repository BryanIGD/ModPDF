"""Qt test setup.

The offscreen platform must be chosen before Qt is imported anywhere, so this
runs at collection time. It lets the whole GUI suite run in CI, on a machine
with no display.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def qt_app() -> Iterator[object]:
    """One QApplication for the whole run; Qt allows only a single instance."""
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def _isolated_default_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect `modpdf.gui.settings`'s bare `QSettings()` — the one a real
    launch uses, reaching the actual per-user preferences file — to a
    private file in `tmp_path` instead, for every GUI test.

    Building a `MainWindow` reads `default_compress_level()` and
    `thumbnail_size()` with no explicit `store` (exactly what a genuine
    caller wants), and a compress-panel test that checks a radio button to
    exercise its behaviour writes one back the same way. Without this, that
    write would land in the real, shared, per-user settings file — leaking
    between test runs and overwriting whatever is on the machine actually
    running the suite. `store=` calls made through the `store` fixture in
    `tests/gui/test_settings.py` already point at their own separate file
    and are untouched by this.
    """
    from PySide6.QtCore import QSettings

    path = str(tmp_path / "isolated-default-settings.ini")

    class _TempBackedQSettings(QSettings):
        def __init__(self, *args: object, **kwargs: object) -> None:
            if args or kwargs:
                # `modpdf.gui.settings` never actually does this — it only ever
                # constructs `QSettings()` bare — but pass through just in case
                # rather than silently ignoring caller-supplied arguments.
                super().__init__(*args, **kwargs)  # type: ignore[call-overload]
            else:
                super().__init__(path, QSettings.Format.IniFormat)

    monkeypatch.setattr("modpdf.gui.settings.QSettings", _TempBackedQSettings)
