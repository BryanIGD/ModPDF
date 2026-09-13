"""Starting the desktop application.

The first thing that happens, before a window exists or an argument is read, is
that the process gives up its ability to reach the network. The GUI gets the
same guarantee as the command line, and for the same reason: it is worth more as
a capability that has been removed than as a promise in a README.
"""

from __future__ import annotations

import sys
from pathlib import Path

from modpdf.security import netguard

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the process exit code."""
    # Before anything else, and with no way to opt out. See modpdf.security.netguard.
    netguard.install()

    # Imported after the guard is installed, so that even Qt starts up inside it.
    from PySide6.QtWidgets import QApplication

    from modpdf.gui import settings as settings_module
    from modpdf.gui import theme
    from modpdf.gui.widgets import app_icon
    from modpdf.gui.window import MainWindow

    arguments = list(sys.argv if argv is None else argv)
    application = QApplication(arguments)
    application.setApplicationName("ModPDF")
    application.setApplicationDisplayName("ModPDF")
    application.setOrganizationName("ModPDF")
    application.setWindowIcon(app_icon())

    # Read once, before the first widget exists — see `theme.set_mode`'s own
    # docstring for why this has to happen here rather than inside the window.
    theme.set_mode(dark=settings_module.dark_mode())

    window = MainWindow()
    window.show()

    # `modpdf-gui somefile.pdf` opens it, so the app can be a file handler.
    for argument in arguments[1:]:
        candidate = Path(argument)
        if candidate.suffix.lower() == ".pdf":
            window.open_path(candidate)
            break

    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
