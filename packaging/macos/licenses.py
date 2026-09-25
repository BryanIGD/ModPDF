"""Collect the license files of everything the macOS app bundles.

The .app ships ModPDF together with Python and every runtime dependency, and
most of their licenses (MIT, BSD, MPL, LGPL) require their text to travel with
a copy like that. This walks ModPDF's full dependency tree, desktop extra
included, and returns every package's license files for PyInstaller to copy
into ModPDF.app/Contents/Resources/THIRD_PARTY_LICENSES.

PySide6, Shiboken6 and the Qt libraries ship no license file in their
packages, so the texts they need are kept in `licenses/` next to this file.
Any other package without a license file stops the build, so a new dependency
can't quietly ship without one.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

HERE = Path(__file__).resolve().parent
DEST = "THIRD_PARTY_LICENSES"

# Packages whose license texts come from `licenses/` instead of their own files.
QT_PACKAGES = {"pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6"}
QT_FILES = ("LGPL-3.0.txt", "GPL-3.0.txt", "PySide6-and-Qt.txt")

_LICENSE_WORDS = ("LICENSE", "LICENCE", "COPYING", "NOTICE")


def runtime_distributions(
    root: str = "modpdf", extras: frozenset[str] = frozenset({"gui"})
) -> dict[str, metadata.Distribution]:
    """Every installed distribution `root[extras]` needs at runtime."""
    found: dict[str, metadata.Distribution] = {}
    pending: list[tuple[str, frozenset[str]]] = [(root, extras)]
    while pending:
        name, wanted = pending.pop()
        key = canonicalize_name(name)
        if key in found:
            continue
        dist = metadata.distribution(name)
        found[key] = dist
        environments = [{"extra": extra} for extra in (wanted or {""})]
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            marker = requirement.marker
            if marker is None or any(marker.evaluate(env) for env in environments):
                pending.append((requirement.name, frozenset(requirement.extras)))
    return found


def _license_files(dist: metadata.Distribution) -> list[tuple[Path, str]]:
    """(absolute source, path under this package's folder) for each file that
    is a license: everything in a `.dist-info/licenses/` folder, plus any
    other non-code file whose name says it is one."""
    files = []
    for entry in dist.files or []:
        parts = entry.parts
        in_licenses_dir = (
            len(parts) > 2 and parts[0].endswith(".dist-info") and parts[1] == "licenses"
        )
        named_like_one = any(word in entry.name.upper() for word in _LICENSE_WORDS)
        if not (in_licenses_dir or named_like_one) or entry.suffix == ".py":
            continue
        # Drop the leading `<name>.dist-info/licenses/` (or the top folder) so
        # the copy sits directly in this package's own folder.
        if in_licenses_dir:
            relative = Path(*parts[2:])
        elif len(parts) > 1:
            relative = Path(*parts[1:])
        else:
            relative = Path(entry.name)
        files.append((Path(str(dist.locate_file(entry))), str(relative)))
    return files


def third_party_license_datas() -> list[tuple[str, str]]:
    """PyInstaller `datas` entries: (source file, destination folder)."""
    datas: list[tuple[str, str]] = []
    missing: list[str] = []

    for key, dist in sorted(runtime_distributions().items()):
        if key in QT_PACKAGES:
            continue
        files = _license_files(dist)
        if not files:
            missing.append(f"{dist.metadata['Name']} {dist.version}")
            continue
        for source, relative in files:
            folder = Path(DEST, dist.metadata["Name"], relative).parent
            datas.append((str(source), str(folder)))

    if missing:
        raise SystemExit(
            "no license file found for: " + ", ".join(missing) + ". Put its license "
            "text in packaging/macos/licenses/ and handle it in licenses.py the way "
            "the Qt packages are, rather than shipping it without one."
        )

    for name in QT_FILES:
        datas.append((str(HERE / "licenses" / name), f"{DEST}/PySide6-and-Qt"))

    # The app bundles Python itself, under the PSF license.
    minor = f"python{sys.version_info.major}.{sys.version_info.minor}"
    python_license = Path(sys.base_prefix, "lib", minor, "LICENSE.txt")
    if not python_license.exists():
        raise SystemExit(f"Python's license file was not found at {python_license}")
    datas.append((str(python_license), f"{DEST}/Python"))

    return datas
