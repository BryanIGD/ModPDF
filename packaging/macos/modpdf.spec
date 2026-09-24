# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS ModPDF.app bundle.

Build with `packaging/macos/build.sh`, which regenerates the icon first and
then runs `pyinstaller packaging/macos/modpdf.spec` from the repo root.

This produces an unsigned, unnotarized .app — fine to run and test on the
machine that built it, but Gatekeeper will refuse it on any other Mac
without a right-click "Open" override. See packaging/macos/README.md for
what real distribution still needs (an Apple Developer ID and `notarytool`)
and why that step is not automated here.
"""

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

# SPECPATH is injected by PyInstaller at exec time — this file's own
# directory, i.e. packaging/macos.
ROOT = Path(SPECPATH).parent.parent  # repo root
ENTRY = ROOT / "src" / "modpdf" / "gui" / "app.py"
ICON = Path(SPECPATH) / "AppIcon.icns"
if not ICON.exists():
    raise SystemExit(f"{ICON} is missing — run make_icon.py first (build.sh does this for you)")

import sys

sys.path.insert(0, str(ROOT / "src"))
from modpdf import __version__  # noqa: E402 — needs the path insert above first

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ModPDF",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ModPDF",
)

app = BUNDLE(
    coll,
    name="ModPDF.app",
    icon=str(ICON),
    bundle_identifier="com.modpdf.ModPDF",
    info_plist={
        "CFBundleName": "ModPDF",
        "CFBundleDisplayName": "ModPDF",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSHumanReadableCopyright": "Apache-2.0 — see NOTICE",
        "NSHighResolutionCapable": True,
        # Lets Finder offer ModPDF under "Open With" for a .pdf, and lets a
        # PDF dragged onto the app icon reach app.py's own argv handling.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "PDF Document",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["com.adobe.pdf"],
                "LSHandlerRank": "Alternate",
            }
        ],
    },
)
