"""Tests that PDFium is only ever entered while holding `PDFIUM_LOCK`.

PDFium is not thread-safe, even across unrelated documents, and a crash from
two threads inside it at once is a native one — timing-dependent, and not
something a test can reliably provoke on demand. So these check the property
that prevents it instead: with the lock held on one thread, work that needs
PDFium on another thread waits for it rather than going ahead. The thumbnail
renderer's version of this is in tests/gui/test_thumbnails.py.
"""

from __future__ import annotations

import threading

import pikepdf

from modpdf.pdfium_lock import PDFIUM_LOCK
from modpdf.verify import verify
from tests.conftest import PageMaker


def test_the_quality_gate_waits_while_someone_else_holds_the_lock(make_pdf: PageMaker) -> None:
    path = make_pdf(1)
    held, release, finished = threading.Event(), threading.Event(), threading.Event()

    def hold_the_lock() -> None:
        with PDFIUM_LOCK:
            held.set()
            release.wait(10)

    def run_the_quality_gate() -> None:
        with pikepdf.open(path) as pdf:
            verify(pdf, pdf)
        finished.set()

    holder = threading.Thread(target=hold_the_lock)
    holder.start()
    assert held.wait(10)
    checker = threading.Thread(target=run_the_quality_gate)
    checker.start()
    try:
        assert not finished.wait(0.5)  # blocked on the lock, not racing
    finally:
        release.set()
    assert finished.wait(10)
    holder.join()
    checker.join()


def test_the_lock_is_reentrant() -> None:
    """Code already holding it can call something that takes it again."""
    with PDFIUM_LOCK, PDFIUM_LOCK:
        pass
