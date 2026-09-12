# ADR-0002: pypdfium2, not PyMuPDF, for rendering

Status: accepted (2026-09-11)

## Context

Compression needs a renderer: the quality gate in `modpdf/verify.py` works by
rendering every page before and after a compression pass and comparing them,
which is the entire basis for claiming compression happens "without
compromising quality" rather than just hoping. `inspect` and the desktop
app's thumbnails need one too. PyMuPDF (`fitz`) is the obvious first choice —
fast, mature, and widely used for exactly this.

## Decision

`pypdfium2`, a binding to Google's PDFium (the renderer inside Chrome), not
PyMuPDF.

## Why

PyMuPDF is licensed AGPL-3.0. Apache-2.0, the license this project uses,
cannot depend on an AGPL component without the AGPL's terms reaching every
downstream user of ModPDF too — effectively converting the whole project's
license by way of one dependency. That is not a tradeoff worth making for a
rendering library when a permissively-licensed one exists.

pypdfium2 wraps PDFium under BSD-3-Clause/Apache-2.0. Same job — page
rendering for the quality gate and for thumbnails — no licensing
entanglement, and it comes from the same rendering engine that already
secures a large share of the world's PDF viewing (Chrome), so it inherits a
comparable hardening track record to QPDF's.

## What we gave up

PyMuPDF's API is generally considered more ergonomic, and it has a larger
community of examples to draw on. Neither of those is worth the licensing
consequence. pypdfium2's API is lower-level, but rendering a page to a bitmap
for a pixel comparison is a small enough surface that this did not turn into
real friction.

## Consequences

- This project's own license claim (Apache-2.0, see LICENSE and NOTICE)
  stays true without a footnote. NOTICE lists pypdfium2 and PDFium alongside
  every other dependency.
- The same reasoning applies to Ghostscript, which was also considered and
  rejected for a different reason: it is AGPL-3.0, and it rewrites PDF
  structure in ways this project cannot audit as it does with QPDF's more
  transparent object model. See ADR-0001 for the QPDF/pikepdf decision this
  parallels.
