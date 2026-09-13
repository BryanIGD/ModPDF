"""The desktop app's own, short list of remembered preferences.

Deliberately not a general config file: everything here is a UI preference —
how the window looks, and one convenience default for a panel a person tends
to use the same way every time — never a document path, a password, or
anything that would turn "no recent-files list" into a promise this module
quietly breaks. Backed by Qt's own `QSettings`, which writes to the
platform's normal per-user application-settings location (the registry on
Windows, a plist on macOS, an ini file under `~/.config` on Linux) — there is
no bespoke file format here to maintain or to explain in a security review.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QSettings

from modpdf.ops.compress import DEFAULT_LEVEL, Level

__all__ = [
    "ThumbnailSize",
    "dark_mode",
    "default_compress_level",
    "set_dark_mode",
    "set_default_compress_level",
    "set_thumbnail_size",
    "thumbnail_size",
]

ThumbnailSize = Literal["small", "medium", "large"]

_DARK_MODE_KEY = "appearance/dark_mode"
_THUMBNAIL_SIZE_KEY = "pages/thumbnail_size"
_COMPRESS_LEVEL_KEY = "compress/default_level"

_DEFAULT_THUMBNAIL_SIZE: ThumbnailSize = "medium"


def dark_mode(*, store: QSettings | None = None) -> bool:
    """Whether the user last chose dark mode, read at startup and again
    whenever the Settings slider flips — see `MainWindow._apply_theme`.

    `store` exists for tests: the default `QSettings()` writes to the real,
    shared, per-user location — exactly what a genuine caller wants, and
    exactly what a test must not touch.
    """
    return bool((store or QSettings()).value(_DARK_MODE_KEY, False, type=bool))


def set_dark_mode(value: bool, *, store: QSettings | None = None) -> None:
    (store or QSettings()).setValue(_DARK_MODE_KEY, value)


def thumbnail_size(*, store: QSettings | None = None) -> ThumbnailSize:
    """How large a page tile is in the Pages grid. See `dark_mode` for why
    `store` exists."""
    value = (store or QSettings()).value(_THUMBNAIL_SIZE_KEY, _DEFAULT_THUMBNAIL_SIZE, type=str)
    if value not in ("small", "medium", "large"):
        return _DEFAULT_THUMBNAIL_SIZE  # an ini hand-edited or from a future version
    return value


def set_thumbnail_size(value: ThumbnailSize, *, store: QSettings | None = None) -> None:
    (store or QSettings()).setValue(_THUMBNAIL_SIZE_KEY, value)


def default_compress_level(*, store: QSettings | None = None) -> Level:
    """The compression tier the Compress panel starts on. Remembered so that
    someone who always picks "Maximum" is not re-picking it every time —
    see `dark_mode` for why `store` exists."""
    value = (store or QSettings()).value(_COMPRESS_LEVEL_KEY, DEFAULT_LEVEL, type=str)
    if value not in ("low", "balanced", "high"):
        return DEFAULT_LEVEL
    return value


def set_default_compress_level(value: Level, *, store: QSettings | None = None) -> None:
    (store or QSettings()).setValue(_COMPRESS_LEVEL_KEY, value)
