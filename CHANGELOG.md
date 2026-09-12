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
