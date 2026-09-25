# ADR-0003: pikepdf, not Ghostscript, for changing PDFs

Status: accepted (2026-09-11)

## Context

Most "compress PDF" tools, online and offline, are Ghostscript underneath.
One command (`gs -sDEVICE=pdfwrite -dPDFSETTINGS=/ebook`) downsamples every
image and writes a smaller file. It was the obvious way to get compression
working on day one.

## Decision

Use pikepdf (bindings to QPDF) for every change ModPDF makes to a PDF, and
write the image recompression ourselves. Ghostscript is not a dependency.

## Why

**Ghostscript rewrites the whole document.** `pdfwrite` doesn't edit a PDF. It
interprets it and writes a brand new one from the result. Fonts get
re-embedded, structure can be dropped or flattened, and forms, bookmarks and
metadata may or may not survive. A tool that promises not to change your
document except where it says so can't be built on a step that regenerates
everything, because we couldn't say which parts it changed. QPDF edits the
objects we ask it to and copies everything else across as it was.

**Its license.** Ghostscript is AGPL-3.0. The same reasoning as ADR-0002
applies: depending on it would pull the whole project under the AGPL.

**Its attack surface.** Ghostscript contains a full PostScript interpreter,
and that interpreter has a long history of sandbox-escape vulnerabilities. A
tool that treats every input PDF as hostile shouldn't route those files
through a programming language interpreter it doesn't need.

**It's an external program.** Calling it means shipping or finding a separate
binary and running it as a subprocess. pikepdf installs with pip like
everything else.

## What we gave up

The easy version of compression. Ghostscript would have given us image
downsampling in one line. Instead, `modpdf/ops/compress.py` finds each image,
works out its effective DPI from the page's transform matrix, picks a codec
based on what's actually in the pixels, and re-encodes it. That's about a
thousand lines we have to maintain, and it's why the quality check in
ADR-0004 had to exist: once we were writing the lossy step ourselves, we
needed a way to prove it didn't damage anything.

## Consequences

- Operations change only what they're supposed to. Splitting a file keeps its
  bookmarks and metadata, and a structural-only compression changes no pixel.
- Compression is our own code, so its bugs are ours too. The CMYK inversion
  problem described in [docs/compression.md](../compression.md) is one we had
  to find and handle ourselves.
