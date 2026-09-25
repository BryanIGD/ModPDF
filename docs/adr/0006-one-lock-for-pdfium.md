# ADR-0006: One process-wide lock for every PDFium call

Status: accepted (2026-09-24)

## Context

PDFium, the renderer behind pypdfium2, is not thread-safe as a library. Two
threads inside it at the same time can crash the process, even when they're
working on different documents.

The desktop app has two threads that use it:

- the thumbnail renderer, which runs on its own thread so a large document
  doesn't freeze the window;
- compression, which runs as a background job. Its quality check (ADR-0004)
  renders every page twice, and flattening a vector-heavy page renders it
  too.

This was hidden until 2026-09-24. Thumbnails were meant to render on a worker
thread, but the window called the renderer directly, so they actually ran on
the UI thread. Fixing that made them truly concurrent, and the next full test
run crashed inside PDFium with the renderer on one thread and a test reading
page text on another.

## Decision

Every PDFium call holds `PDFIUM_LOCK`, a reentrant lock in
`modpdf/pdfium_lock.py`. That includes opening and closing documents and
freeing pages and bitmaps, since those are PDFium calls too. The easiest way
to get that right is to do the work in a function called inside the `with`
block, so everything it created is freed before the lock is released.

## Alternatives considered

- **One dedicated PDFium thread** that every caller sends work to. Cleaner in
  theory, but `verify.py` and `compress.py` are ordinary synchronous code that
  the command line uses too. Routing them through a Qt thread would reshape
  both for the sake of the desktop app.
- **Running each job in its own process.** This is the real fix for isolation
  in general, and it's still planned (see "Not built yet" in the README). It's
  a much bigger change than this problem needs.
- **Not rendering thumbnails while compressing.** A rule like that is easy to
  break by accident, and nothing would enforce it.

## What we gave up

- No parallel rendering. Thumbnails pause while a compression's quality check
  holds the lock, and continue when it finishes. The window itself stays
  responsive, because the UI thread never waits on the lock.
- The command line is single-threaded, so for it the lock does nothing and
  costs nothing.

## Consequences

- Any new code that uses pypdfium2 must take the lock.
  `tests/unit/test_pdfium_lock.py` fails if a module under `src/modpdf`
  imports pypdfium2 without also using `PDFIUM_LOCK`, and checks that the
  quality check waits for the lock. `tests/gui/test_thumbnails.py` checks the
  renderer does too.
- A crash like this can't be reproduced reliably on demand, so the tests check
  that the lock is respected rather than trying to provoke the crash.
