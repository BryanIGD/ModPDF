"""Qt test setup.

The offscreen platform must be chosen before Qt is imported anywhere, so this
runs at collection time. It lets the whole GUI suite run in CI, on a machine
with no display.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def qt_app() -> Iterator[object]:
    """One QApplication for the whole run; Qt allows only a single instance."""
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application
