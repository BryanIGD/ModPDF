#!/usr/bin/env bash
# Build an unsigned, local ModPDF.app for macOS.
#
# Usage: packaging/macos/build.sh
# Output: dist/ModPDF.app (repo root's dist/, already gitignored)
#
# What this does NOT do: sign or notarize the bundle. Without a Developer ID
# certificate, Gatekeeper refuses the result on any Mac but the one that
# built it — see README.md in this directory for what real distribution
# still needs.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
venv_python="$root/.venv/bin/python3"

if [[ ! -x "$venv_python" ]]; then
    echo "error: $venv_python not found — set up the project's venv first (see README.md)" >&2
    exit 1
fi

if ! "$venv_python" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller is not installed in .venv — installing it now (see this directory's" \
        "README.md for why it is not part of the project's locked dependency groups)"
    "$venv_python" -m pip install pyinstaller
fi

echo "== generating AppIcon.icns from the app's own drawn mark =="
"$venv_python" "$here/make_icon.py"

echo "== running PyInstaller =="
cd "$root"
"$venv_python" -m PyInstaller --noconfirm --clean "$here/modpdf.spec"

echo
echo "built: $root/dist/ModPDF.app"
echo "run it with: open dist/ModPDF.app"
