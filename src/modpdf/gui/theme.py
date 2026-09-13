"""The application's palette and Qt stylesheet.

Colours come from the application icon: slate carries structure and weight,
steel blue marks what is live — selection, focus, active state. Everything else
is a neutral derived from the slate, so the greys sit in the same hue family as
the brand rather than fighting it.

Colour means something here. Blue is state; amber, red and green are reserved
for safety findings and nothing else. Nothing is coloured for decoration.

Two palettes, not one: light (the default) and dark, switched by `set_mode`.
Everything below except `SLATE` is reassigned when the mode changes — every
module that does `from modpdf.gui import theme` and reads `theme.INK_2` (an
attribute lookup, not a name bound once at import time) sees the new value
without needing to know a theme even exists. `SLATE` is deliberately left out
of the swap: it is the fixed dark anchor behind the "Primary" button and the
tooltip background in both modes, not a text colour that needs to invert.
"""

from __future__ import annotations

# The one colour that does not switch with the mode — see the module
# docstring. Used only for the "Primary" button background and the tooltip
# background, both solid, dark chrome regardless of theme.
SLATE = "#2E3742"

_LIGHT = {
    "BLUE": "#5B82B0",
    "BLUE_DARK": "#3F618A",
    "BLUE_SOFT": "#E7EDF5",
    "BG": "#F4F5F7",
    "PANEL": "#FFFFFF",
    "RAIL": "#EBEEF2",
    "LINE": "#DBDFE6",
    "LINE_SOFT": "#E6E9EF",
    "SURFACE": "#FAFBFC",
    "INK": "#2E3742",
    "INK_2": "#5B6674",
    "INK_3": "#8992A0",
    "CONTROL_LINE": "#C6CDD7",
    "WARN": "#8A5A0F",
    "WARN_SOFT": "#FBF2E2",
    "WARN_LINE": "#E9D6B2",
    "BAD": "#A03A3A",
    "BAD_SOFT": "#FBEFEF",
    "BAD_LINE": "#EBD2D2",
    "GOOD": "#2F6A54",
    "GOOD_SOFT": "#E9F1EE",
    "GOOD_LINE": "#C7DCD5",
}

_DARK = {
    "BLUE": "#7CA6D9",
    "BLUE_DARK": "#BFD8F5",
    "BLUE_SOFT": "#26374A",
    "BG": "#1C2027",
    "PANEL": "#242932",
    "RAIL": "#20242B",
    "LINE": "#333A45",
    "LINE_SOFT": "#2B313A",
    "SURFACE": "#2B313A",
    "INK": "#E7EAEF",
    "INK_2": "#AEB6C2",
    "INK_3": "#7B8492",
    "CONTROL_LINE": "#454E5C",
    "WARN": "#E5B567",
    "WARN_SOFT": "#3A2E17",
    "WARN_LINE": "#5C4A26",
    "BAD": "#E28686",
    "BAD_SOFT": "#3A2020",
    "BAD_LINE": "#5C3232",
    "GOOD": "#7FCBA4",
    "GOOD_SOFT": "#1E3327",
    "GOOD_LINE": "#345745",
}

# Every name _LIGHT and _DARK define must match exactly, or a mode switch
# would leave a stale attribute behind from whichever loaded first. A plain
# `assert` would be stripped under `-O`, silently dropping this check, so
# this is a real, always-on condition instead.
if set(_LIGHT) != set(_DARK):
    raise ValueError("_LIGHT and _DARK must define exactly the same names")

# Bound from `_LIGHT` here, and only ever reassigned as a whole group by
# `set_mode` below (never touched one name at a time) — real assignments, not
# bare annotations, so a plain reader, ruff and mypy alike all see these as
# genuinely defined module attributes rather than names that exist by
# convention only.
BLUE = _LIGHT["BLUE"]
BLUE_DARK = _LIGHT["BLUE_DARK"]
BLUE_SOFT = _LIGHT["BLUE_SOFT"]
BG = _LIGHT["BG"]
PANEL = _LIGHT["PANEL"]
RAIL = _LIGHT["RAIL"]
LINE = _LIGHT["LINE"]
LINE_SOFT = _LIGHT["LINE_SOFT"]
SURFACE = _LIGHT["SURFACE"]
INK = _LIGHT["INK"]
INK_2 = _LIGHT["INK_2"]
INK_3 = _LIGHT["INK_3"]
CONTROL_LINE = _LIGHT["CONTROL_LINE"]
WARN = _LIGHT["WARN"]
WARN_SOFT = _LIGHT["WARN_SOFT"]
WARN_LINE = _LIGHT["WARN_LINE"]
BAD = _LIGHT["BAD"]
BAD_SOFT = _LIGHT["BAD_SOFT"]
BAD_LINE = _LIGHT["BAD_LINE"]
GOOD = _LIGHT["GOOD"]
GOOD_SOFT = _LIGHT["GOOD_SOFT"]
GOOD_LINE = _LIGHT["GOOD_LINE"]

_dark_mode = False


def set_mode(*, dark: bool) -> None:
    """Switch the whole module's palette. Must run before anything reads a
    colour from it — a caller that has already built widgets from the old
    values (baked into an f-string) will not see this update; see `app.py`,
    which calls this before the first widget exists, and the "restart to
    apply" note in the settings dialog, which exists for the same reason."""
    global _dark_mode
    _dark_mode = dark
    globals().update(_DARK if dark else _LIGHT)


def is_dark() -> bool:
    return _dark_mode


def mono_family() -> str:
    """The platform's fixed-width font, as Qt knows it.

    Naming families directly ("SF Mono", Consolas) means guessing what is
    installed and warning on every platform that guesses wrong. Qt already
    knows which font the system uses for fixed-width text, so ask it.
    """
    from PySide6.QtGui import QFontDatabase

    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def stylesheet() -> str:
    """The application-wide Qt style sheet."""
    return f"""
    QWidget {{
        background: {BG};
        color: {INK};
        font-size: 13px;
    }}
    QLabel {{ background: transparent; }}

    #Header {{ background: {RAIL}; border-bottom: 1px solid {LINE}; }}
    #Toolbar {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
    #StatusBar {{ background: {RAIL}; border-top: 1px solid {LINE}; }}
    #Inspector {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
    #Card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; }}
    #DropZone {{
        background: {PANEL}; border: 2px dashed {CONTROL_LINE}; border-radius: 14px;
    }}

    QPushButton {{
        background: {PANEL};
        border: 1px solid {LINE};
        border-radius: 5px;
        padding: 5px 11px;
        color: {INK};
    }}
    QPushButton:hover {{ background: {SURFACE}; border-color: {CONTROL_LINE}; }}
    QPushButton:pressed {{ background: {RAIL}; }}
    QPushButton:disabled {{ color: {INK_3}; background: {RAIL}; border-color: {LINE}; }}

    QPushButton#Primary {{
        background: {SLATE}; border-color: {SLATE}; color: #FFFFFF; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: #3A4551; border-color: #3A4551; }}
    QPushButton#Primary:disabled {{ background: {INK_3}; border-color: {INK_3}; color: {RAIL}; }}

    QPushButton#Tool {{
        background: transparent; border: 1px solid transparent;
        border-bottom: 2px solid transparent; color: {INK_2};
        border-radius: 6px; padding: 6px 12px;
    }}
    QPushButton#Tool:hover {{ background: {PANEL}; color: {INK}; }}
    QPushButton#Tool:checked {{
        background: {BLUE_SOFT}; color: {BLUE_DARK}; font-weight: 600;
        border-bottom: 2px solid {BLUE};
    }}
    QPushButton#Tool:disabled {{ background: transparent; border-color: transparent; }}

    QPushButton#Chrome {{
        background: transparent; border: none; color: {INK_2}; padding: 4px 6px;
    }}
    QPushButton#Chrome:hover {{ color: {INK}; text-decoration: underline; }}

    QListWidget {{
        background: {BG}; border: none; outline: none;
    }}
    QListWidget::item {{ border: none; }}
    QListWidget::item:selected {{ background: transparent; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {CONTROL_LINE}; border-radius: 5px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {INK_3}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QLineEdit, QSpinBox {{
        background: {PANEL}; border: 1px solid {CONTROL_LINE};
        border-radius: 5px; padding: 4px 8px; selection-background-color: {BLUE};
    }}
    QLineEdit:focus, QSpinBox:focus {{ border-color: {BLUE}; }}

    QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}

    QToolTip {{
        background: {SLATE}; color: #FFFFFF; border: none;
        padding: 5px 8px; border-radius: 4px;
    }}
    """
