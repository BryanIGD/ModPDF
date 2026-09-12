# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing tagged yet. The first release will be 0.1.0.

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
  saying so — the moment any page looks different enough to matter. Oversized
  images are downsampled and re-encoded with the codec their actual pixel
  values call for: CCITT Group 4 for anything overwhelmingly near-black or
  near-white, whatever colour space it happens to be stored in, JPEG for
  genuine photographs. CMYK images, indexed images and anything carrying a
  transparency mask are left untouched rather than risked. `--lossless` and
  `--target-dpi` included.
- A desktop application (`modpdf-gui`, optional extra `modpdf[gui]`, PySide6):
  page thumbnails with selection, drag-to-reorder (tracked by the mouse
  directly rather than through Qt's own drag-and-drop, which does not
  reliably initiate a session at all), delete, duplicate, extract, split by
  a fixed interval or by hand-built page ranges, compress, sanitize and
  merge-by-dropping. Edits are held in memory as an ordering of the source
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

### Changed

- Whole operations moved into `modpdf/tasks.py`, which the command line and the
  desktop app both call. Neither interface implements a PDF operation of its own,
  and neither can reach the filesystem without the security layer.
- `Pdf.save` options can now be threaded through `document.save_pdf`, so a
  caller that computed a file's size with particular save options (compression
  does, for its structural pass) writes the file with the same ones — the
  number in a report always matches the number on disk.

### Fixed

- A desktop-app background job started from inside another job's own
  completion callback — exactly what adding a second file does, by opening
  the combined result it just wrote — could vanish silently: nothing kept the
  first job's Python object alive between it emitting its result and the main
  thread actually receiving it, so it was sometimes garbage collected in
  between and the window was left saying "Adding…" forever, with no error.
  `workers.run` now holds a reference to every job until its result has
  actually been delivered.
