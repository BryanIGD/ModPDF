"""One lock for every call into PDFium, process-wide.

PDFium is not thread-safe as a library, not merely per document: two threads
inside it at once, even working on unrelated documents, can crash the process.
pypdfium2's own documentation says as much. The desktop app has two places that
can run at the same time — the thumbnail renderer's thread, and a background
job compressing a file, whose quality gate renders every page twice — so every
PDFium call in this project is made while holding this lock.

Hold it for as long as any pypdfium2 object is alive, including the moment one
is closed or freed: releasing a page or a bitmap is a PDFium call too. The
simplest way to get that right is to do the work in a function called from
inside the `with` block, so every object that function created is gone by the
time it returns. Reentrant, so code already holding it can call something that
takes it again.

The command line is single-threaded and never contends for it; there the lock
costs nothing.
"""

from __future__ import annotations

import threading

__all__ = ["PDFIUM_LOCK"]

PDFIUM_LOCK = threading.RLock()
