# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-09-25

### Fixed

- The macOS app now includes the license text of everything it bundles:
  Python, PySide6 and Qt, and every package ModPDF depends on, in
  `ModPDF.app/Contents/Resources/THIRD_PARTY_LICENSES`. The 0.1.0 and 0.1.1
  app downloads were missing them, and `NOTICE` wrongly said PySide6 is never
  bundled. The build now stops if any bundled package has no license file.
- `SECURITY.md` said there was no release yet and pointed to a README section
  that no longer exists.

### Changed

- PyPI lists BryanIGD as the author, and links to the source code, issue
  tracker, changelog and security policy.
- The README says where to download the Mac app, and that it's built for
  Apple Silicon.
- `CONTRIBUTING.md` explains how to make a release.

## [0.1.1] - 2026-09-25

### Fixed

- In the desktop app, a long file name could push the whole right-hand panel
  wider than the window, cutting off every value and button on its right side.
  File names have no spaces to wrap at, and each panel's scroll area was sizing
  its content to the widest label instead of to the panel. Panels now always
  take the panel's width, and long file names are shortened in the middle
  (`Ley-Orgánica-…icaciones.pdf`) with the full name on hover. This came in
  with 0.1.0's scrollable panels.
- The header showed a small file's size as "0.0 MB". It now uses KB or MB, the
  same as the Document card.

## [0.1.0] - 2026-09-25

### Added

- `split`, `merge` and `reorder`. Page numbers are 1-based and inclusive, with
  `-1` for the last page and `12-` for "to the end".
- Bookmarks are rebuilt against the new page order instead of being dropped.
  Entries orphaned by a removed parent heading are promoted rather than deleted,
  and named destinations are resolved from both `/Dests` and `/Names`.
- `inspect`, which reports what a PDF contains besides its pages: JavaScript,
  automatic actions, embedded attachments, XFA forms, outbound links, metadata,
  and earlier revisions still recoverable inside the file. `--json` included.
- `sanitize`, which removes all of the above by rebuilding the document from its
  pages, so payloads are absent from the output rather than merely unreferenced.
  Plain links are kept unless `--strip-links` is given.
- An enforced no-network guarantee. The process replaces its own socket, DNS and
  TLS entry points with ones that refuse, and the test suite asserts both that
  network calls fail and that PDF work still succeeds while they do.
- Warnings when output is written into an iCloud Drive, Dropbox, Google Drive or
  OneDrive folder, because a local-only tool writing into a sync folder is not
  local in any way the user cares about.
- Reporting when QPDF had to repair a damaged file, so a silently reconstructed
  document is not mistaken for an intact one.
- Encrypted documents, via `--password-stdin` or `MODPDF_PASSWORD`. There is
  deliberately no flag that takes a password as its value.
- File-size and page-count limits on every input, with clear refusals.
- Atomic, mode-0600 output writing; split directories at mode 0700.
- `compress`, with a quality gate (`modpdf/verify.py`) that renders every page
  before and after and compares them, falling back to a lossless result — and
  saying so — the moment any page looks different enough to matter.
- Oversized images are downsampled and re-encoded with the codec their actual
  pixel values call for: CCITT Group 4 for anything overwhelmingly near-black
  or near-white, whatever colour space it happens to be stored in, JPEG for
  genuine photographs. CMYK images, indexed images and anything carrying a
  transparency mask are left untouched rather than risked.
- `--lossless` and three tuned `--level` presets (`low`, `balanced`, `high`),
  rather than a raw DPI number to guess at. Only `high` is allowed to accept
  a more visibly different result in exchange for a smaller file; `low` and
  `balanced` both still promise no visible loss.
- `high` re-encodes every eligible image even when it was not oversized.
  Otherwise a document whose images were already reasonably sized had
  nothing left for "maximum compression" to do beyond what `balanced`
  already did, and the report says so when that happens.
- `balanced` and `high` can also rasterize a page whose own vector content —
  not an image at all, a complex diagram exported as drawing commands — is
  heavy enough to be worth it, each at its own resolution and JPEG quality,
  since no image setting touches vector art. Every character of text on that
  page, including text that is itself part of the diagram, stays exactly as
  it was and stays selectable. `low` never does this. `balanced`'s flattened
  result still has to clear the same strict quality gate as everything else
  it does, so this did not loosen its no-visible-loss promise; only `high`
  widens what the gate will accept.
- `high`'s own image resolution and JPEG quality are kept deliberately close
  to lossless — an early, more aggressive version made a flattened diagram's
  own text hard to read. One consequence worth knowing: on an ordinary photo
  or scan with no vector page to flatten, `high` has little left to trade,
  and `balanced` can end up producing the smaller file.
- A desktop application (`modpdf-gui`, optional extra `modpdf[gui]`, PySide6):
  page thumbnails with selection, drag-to-reorder (tracked by the mouse
  directly rather than through Qt's own drag-and-drop, which does not
  reliably initiate a session at all), delete, duplicate, extract, split by
  hand-built page ranges, compress, sanitize and merge-by-dropping. Edits are held in memory as an ordering of the source
  pages, so nothing is written until you save and Revert is free. Thumbnails
  are never written to disk and no recent-files list is kept.
- The desktop app's Open button now builds a workspace out of more than one
  file: with a document already open, choosing (or dropping) another one adds
  its pages after the first's instead of replacing it, honouring whatever
  reordering or deletion was already pending. No second button — Open is
  overloaded rather than duplicated, since "bring this file into the
  workspace" is one action either way. Backed by `tasks.append_document` and
  a private, per-window `0700` scratch directory
  (`security/fs.private_scratch_dir`) that is removed when the window closes.

- A Settings dialog in the desktop app, behind a gear in the header: thumbnail
  size (small, medium or large), the compression level the Compress panel
  starts on, and light or dark. Every choice applies immediately. Switching
  theme rebuilds the window in place and keeps the open document, page
  selection, active panel, split ranges and compress choice as they were.
  The three values are stored in the operating system's own per-user
  settings location (`modpdf/gui/settings.py`). They are the only thing the
  app remembers between runs, and none of them is a path or anything else
  about a document.
- `packaging/macos/build.sh`, which builds an unsigned `ModPDF.app` with
  PyInstaller. Its icon is generated from the same drawn mark the window
  uses, so there is still no image asset in the repository. Signing and
  notarization are not done yet; see `packaging/macos/README.md`.

- A release workflow. Pushing a version tag publishes to PyPI with Trusted
  Publishing (no API token exists to leak), then creates a GitHub Release
  with the package files, a CycloneDX SBOM of every runtime dependency, and
  an unsigned macOS app. Running it by hand publishes to TestPyPI as a dry
  run.
- `bandit` now runs in pre-commit, on the same files the security workflow
  scans.
- ADRs for pikepdf over Ghostscript, the compression quality gate, blocking
  the network at runtime, and the PDFium lock. `docs/compression.md` holds the
  compression details that used to fill most of the README.

### Changed

- The README was rewritten to be shorter, with screenshots at the top.
- The desktop app's layout was redesigned: a new header and toolbar, a
  drop-zone empty state, a document details card, and a set of line icons
  drawn in code (`modpdf/gui/icons.py`) rather than loaded from files or an
  icon font.

- Whole operations moved into `modpdf/tasks.py`, which the command line and the
  desktop app both call. Neither interface implements a PDF operation of its own,
  and neither can reach the filesystem without the security layer.
- `Pdf.save` options can now be threaded through `document.save_pdf`, so a
  caller that computed a file's size with particular save options (compression
  does, for its structural pass) writes the file with the same ones — the
  number in a report always matches the number on disk.

### Fixed

- `inspect` always reported "0 images". Its scan skipped every object that
  wasn't a plain dictionary, and an image is always a stream. Soft masks are
  not counted as images of their own, so a transparent picture counts once.
- In dark mode, radio buttons were invisible until checked: the platform style
  drew their rings in light-theme grey. They're now drawn by the app's own
  stylesheet in both themes.
- Hints under the Compress panel's options could lose their second line. The
  indent was stylesheet padding, which QLabel's word wrap doesn't measure, and
  a panel taller than the window was squashed to fit. Hints now use a real
  margin, and every inspector panel scrolls when it doesn't fit.

- The desktop app rendered every page thumbnail on its own window thread, so
  opening a large document froze the window until the last page was done.
  The renderer had been moved to a worker thread and then called directly —
  and a direct call runs on the caller's thread regardless. Requests now go
  out as queued signals. Each carries a generation number, so a thumbnail
  still arriving for a document or size that has since been replaced is
  dropped instead of landing on the wrong tile.
- PDFium is not thread-safe, even across unrelated documents, and the desktop
  app could enter it from two threads at once: the thumbnail renderer, and a
  compression running in the background whose quality gate renders every
  page. That can crash the whole process. Every PDFium call now holds one
  process-wide lock (`modpdf/pdfium_lock.py`). The command line is
  single-threaded, so the lock costs it nothing.

- A desktop-app background job started from inside another job's own
  completion callback — exactly what adding a second file does, by opening
  the combined result it just wrote — could vanish silently: nothing kept the
  first job's Python object alive between it emitting its result and the main
  thread actually receiving it, so it was sometimes garbage collected in
  between and the window was left saying "Adding…" forever, with no error.
  `workers.run` now holds a reference to every job until its result has
  actually been delivered.

[Unreleased]: https://github.com/BryanIGD/ModPDF/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/BryanIGD/ModPDF/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/BryanIGD/ModPDF/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/BryanIGD/ModPDF/releases/tag/v0.1.0
