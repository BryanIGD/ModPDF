# Building ModPDF.app

```
packaging/macos/build.sh
```

This regenerates `AppIcon.icns` from the app's own drawn mark (see
`make_icon.py`), then runs PyInstaller against `modpdf.spec`. The result
lands at `dist/ModPDF.app`, from the repo root — open it with `open
dist/ModPDF.app`, or double-click it in Finder.

## What this gives you, and what it doesn't

The result runs, and is genuinely offline the same way `modpdf-gui` from a
normal install is — freezing the app doesn't change when `netguard.install()`
runs, which is still the first thing `app.py` does. Good for testing a build
on your own machine, or handing it directly to someone who trusts you enough
to allow it in System Settings → Privacy & Security → Open Anyway.

It is **unsigned and unnotarized**. Apple's Gatekeeper will refuse to open it
normally on any Mac other than the one that built it ("ModPDF.app is damaged
and can't be opened" — misleading; it isn't damaged, just unsigned). Real
distribution — a `.dmg` someone downloads and just opens — needs:

1. An Apple Developer ID (the paid Developer Program, not a free Apple ID).
2. Code-signing the bundle with that ID (`codesign`).
3. Submitting it to Apple for notarization (`notarytool`) and stapling the
   result (`stapler`).

None of that is automated, because it needs credentials that belong to
whoever releases the app. The release workflow (`.github/workflows/release.yml`)
builds this same unsigned app on an Apple Silicon runner and attaches it to
each GitHub Release; signing would slot in there once there's a Developer ID.

## Licenses inside the app

The app bundles Python, PySide6/Qt and every package ModPDF depends on, and
their licenses require their text to travel with it. `licenses.py` walks the
full dependency tree at build time and copies each package's license files
into `ModPDF.app/Contents/Resources/THIRD_PARTY_LICENSES`. PySide6 and Qt ship
no license file of their own, so their texts (LGPL-3.0, and the GPL-3.0 it
builds on) are kept in `licenses/` here. If any other bundled package has no
license file, the build stops rather than shipping without it.

## Why PyInstaller is not part of `uv.lock`

It's installed straight into `.venv` by `build.sh` (or by hand:
`.venv/bin/pip install pyinstaller`) rather than added to a `pyproject.toml`
dependency group. Adding a group properly needs `uv lock` to run, so the new
group's hashes land in `uv.lock` — otherwise `uv sync --locked`, which CI
uses, breaks on every install. Once `uv` is available wherever this is next
touched, promoting it to a real `packaging` dependency group (`uv add
--group packaging pyinstaller`) is the right long-term fix.
