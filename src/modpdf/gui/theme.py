"""The application's palette and Qt stylesheet.

Colours come from the application icon: slate carries structure and weight,
steel blue marks what is live — selection, focus, active state. Everything else
is a neutral derived from the slate, so the greys sit in the same hue family as
the brand rather than fighting it.

Colour means something here. Blue is state; amber, red and green are reserved
for safety findings and nothing else. Nothing is coloured for decoration.
"""

from __future__ import annotations

# Brand, straight off the icon.
SLATE = "#2E3742"
BLUE = "#5B82B0"
BLUE_DARK = "#3F618A"
BLUE_SOFT = "#E7EDF5"

# Neutrals, derived from the slate so the greys stay in its hue family.
BG = "#F4F5F7"
PANEL = "#FFFFFF"
RAIL = "#EBEEF2"
LINE = "#DBDFE6"
LINE_SOFT = "#E6E9EF"
SURFACE = "#FAFBFC"
INK = "#2E3742"
INK_2 = "#5B6674"
INK_3 = "#8992A0"
CONTROL_LINE = "#C6CDD7"

# Safety findings only.
WARN = "#8A5A0F"
WARN_SOFT = "#FBF2E2"
WARN_LINE = "#E9D6B2"
BAD = "#A03A3A"
BAD_SOFT = "#FBEFEF"
BAD_LINE = "#EBD2D2"
GOOD = "#2F6A54"
GOOD_SOFT = "#E9F1EE"
GOOD_LINE = "#C7DCD5"


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
        background: transparent; border: 1px solid transparent; color: {INK_2};
    }}
    QPushButton#Tool:hover {{ background: {PANEL}; border-color: {LINE}; color: {INK}; }}
    QPushButton#Tool:checked {{
        background: {PANEL}; border-color: {LINE}; color: {INK}; font-weight: 600;
    }}

    QListWidget {{
        background: {BG}; border: none; outline: none;
    }}
    QListWidget::item {{ border: none; }}
    QListWidget::item:selected {{ background: transparent; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: #C2C9D3; border-radius: 5px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #AAB3C0; }}
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
