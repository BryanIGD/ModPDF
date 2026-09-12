"""The ModPDF desktop application.

This package contains no PDF logic. Every operation it performs is a call into
`modpdf.ops`, `modpdf.document` or `modpdf.inspection` — the same functions the
command line calls. That is the point: a bug fixed for one interface is fixed
for both, and the security layer cannot be bypassed by coming in through a
window instead of a terminal.

Importing this package requires the optional GUI extra (`pip install modpdf[gui]`).
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    """Entry point for the `modpdf-gui` console script."""
    from modpdf.gui.app import main as run

    return run()
