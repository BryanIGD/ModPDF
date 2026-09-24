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
to right-click → Open past Gatekeeper's warning.

It is **unsigned and unnotarized**. Apple's Gatekeeper will refuse to open it
normally on any Mac other than the one that built it ("ModPDF.app is damaged
and can't be opened" — misleading; it isn't damaged, just unsigned). Real
distribution — a `.dmg` someone downloads and just opens — needs:

1. An Apple Developer ID (the paid Developer Program, not a free Apple ID).
2. Code-signing the bundle with that ID (`codesign`).
3. Submitting it to Apple for notarization (`notarytool`) and stapling the
   result (`stapler`).

None of that is automated here, because it needs credentials that belong to
whoever is actually releasing the app, not something to bake into a build
script. When ModPDF has a release process, that's ADR-worthy on its own —
see the project's `docs/adr/` for the pattern.

## Why PyInstaller is not part of `uv.lock`

It's installed straight into `.venv` by `build.sh` (or by hand:
`.venv/bin/pip install pyinstaller`) rather than added to a `pyproject.toml`
dependency group. Adding a group properly needs `uv lock` to run, so the new
group's hashes land in `uv.lock` — otherwise `uv sync --locked`, which CI
uses, breaks on every install. Once `uv` is available wherever this is next
touched, promoting it to a real `packaging` dependency group (`uv add
--group packaging pyinstaller`) is the right long-term fix.
