# ADR-0001: Python, not Go or Rust

Status: accepted (2026-09-11)

## Context

ModPDF needs to read, restructure and rewrite PDF files. We had to pick an
implementation language before writing anything else.

The constraint that dominates every other consideration: **we are not going to
write a PDF parser.** PDF is a thousand-page specification, real files violate
it constantly, and malformed PDFs are a well-established malware delivery
vector. Anything we wrote ourselves would be both less correct and less safe
than the C++ parsers that have been hardened against hostile input for two
decades. So the real question is not "which language is nicest" but "which
language has the best bindings to QPDF and PDFium".

## Decision

Python 3.11 or newer.

## Why

`pikepdf` is a mature, actively maintained binding to QPDF, and QPDF is the
best structural PDF tool that exists. Splitting, merging, reordering, object
and cross-reference stream optimization, and encryption handling are precisely
what it was built to do, and pikepdf exposes the PDF object model directly
rather than through an abstraction that loses information.

`pypdfium2` gives us Chromium's PDF renderer under a permissive license. This
matters more than it first appears: rendering is what lets us verify that a
compressed file still looks like the original, and that verification is the
entire basis of our claim to compress "without compromising quality". Without
a renderer we would be guessing.

Python's testing ecosystem also fits this problem unusually well. PDF
operations have clean algebraic properties — splitting and then merging should
reproduce the original page order, reordering by an identity permutation should
change nothing — and Hypothesis lets us test those properties across generated
inputs rather than a handful of examples.

## What we gave up

Distribution. A person who is not a developer does not have a Python runtime,
and `pip install` is not an answer for them. Go would have produced a single
static binary, and `pdfcpu` is a respectable library.

We accepted this because the distribution problem is solvable with known tools
(PyInstaller, plus code signing and notarization) and is scheduled as its own
phase, whereas building on a weaker PDF foundation is not something you can fix
later. Rust was ruled out separately: `lopdf` and `pdf-rs` are not close to
QPDF in completeness, and closing that gap ourselves would have cost months and
reintroduced the parser-writing risk above.

Runtime performance was never a real factor. The expensive work happens inside
QPDF, PDFium and libjpeg, all of which are C or C++. Python orchestrates; it
does not decode a 4000x3000 scan.

## Consequences

- We inherit QPDF's and PDFium's security track record, which is much better
  than anything we would have achieved alone, and their CVEs, which we must
  track. `pip-audit` runs on every pull request for this reason.
- Dependency licensing becomes a design constraint rather than an afterthought.
  PyMuPDF, which is excellent, is AGPL-3.0 and would have forced this project
  and everyone downstream into AGPL. We use pypdfium2 instead. See ADR-0002.
- Phase 5 of the build plan exists solely to pay off the distribution debt.
