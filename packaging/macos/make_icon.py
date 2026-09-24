"""Generate the macOS .icns app icon from the app's own drawn mark.

The mark is drawn in code (`modpdf.gui.widgets.mark_pixmap`), not loaded from
an image file — see that module's docstring for why. This script is the
bridge from "drawn in code" to the one binary asset a macOS app bundle
actually requires: an .icns file, referenced by Info.plist. Run it before
building the .app (see build.sh, which does this for you).

macOS-only: it shells out to `iconutil`, an Apple command-line tool with no
cross-platform equivalent — one more reason app icon generation lives under
packaging/macos rather than somewhere platform-neutral.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — a fixed, resolved-path call to iconutil below, no shell
import sys
from pathlib import Path

# Apple's required set for an .iconset folder: a base size and its @2x
# render, for each of five named sizes. See `iconutil --help`.
_ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def main() -> int:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        print("error: iconutil not found — this script only runs on macOS", file=sys.stderr)
        return 1

    # Imported here, after the platform check, and with the offscreen
    # platform forced — this script never needs a real window, and forcing
    # it means it also runs over SSH or in CI with no display attached.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    # A QPixmap needs a QApplication to exist, even one that never shows a
    # window — kept alive for the rest of this function by staying in scope.
    _application = QApplication.instance() or QApplication([])

    from modpdf.gui.widgets import mark_pixmap

    here = Path(__file__).parent
    iconset_dir = here / "AppIcon.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir()

    for name, size in _ICONSET_SIZES.items():
        # No ink_color override: the default is theme.SLATE, the one colour
        # that never follows the in-app light/dark setting — correct here,
        # since this icon sits on the OS's own dock and Finder chrome, not
        # this app's window. See mark_pixmap's own docstring.
        if not mark_pixmap(size).save(str(iconset_dir / name)):
            print(f"error: failed to write {name}", file=sys.stderr)
            return 1

    # iconutil's resolved path (above) and fixed arguments, never a shell —
    # safe despite what a generic subprocess-call scanner assumes.
    icns_path = here / "AppIcon.icns"
    subprocess.run(  # noqa: S603 # nosec B603
        [iconutil, "--convert", "icns", str(iconset_dir), "--output", str(icns_path)],
        check=True,
    )
    shutil.rmtree(iconset_dir)

    print(f"wrote {icns_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
