"""Refusing inputs that would exhaust the machine.

Every PDF ModPDF opens is treated as hostile, because PDFs genuinely are a
malware and denial-of-service vector, and the file a user drags in is often one
a stranger emailed them. QPDF and PDFium are hardened against malformed input
far better than anything we would write, but neither of them knows that a
forty-gigabyte file or a document claiming two million pages is not worth
attempting — that judgement is ours.

The defaults are deliberately generous. They exist to stop a pathological file
from taking the machine down, not to second-guess anyone's real documents: a
scanned thousand-page deposition is nowhere near them.

What is deliberately absent: a wall-clock timeout. A timeout that works needs to
be able to kill work already running inside a native library, and from inside
this process it cannot — a signal handler does not run until control returns to
Python, so a genuinely stuck decode would ignore it. Doing that properly needs
the work in a subprocess, which the build plan defers until a real case calls
for it. Shipping a timeout that silently fails to fire would be worse than
having none, so there is none.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["DEFAULT_LIMITS", "LimitExceededError", "Limits", "check_file_size", "check_page_count"]


class LimitExceededError(Exception):
    """An input is larger than ModPDF is willing to attempt."""


@dataclass(frozen=True)
class Limits:
    """Ceilings on what a single document may be.

    Attributes:
        max_file_bytes: Largest file to open at all.
        max_pages: Most pages to accept in one document.
    """

    max_file_bytes: int = 4 * 1024**3  # 4 GiB
    max_pages: int = 100_000


DEFAULT_LIMITS = Limits()


def check_file_size(path: Path, limits: Limits = DEFAULT_LIMITS) -> None:
    """Refuse a file too large to open, before anything tries to read it."""
    size = path.stat().st_size
    if size > limits.max_file_bytes:
        raise LimitExceededError(
            f"{path.name} is {_human(size)}, above the {_human(limits.max_file_bytes)} "
            f"limit. If this is a real document rather than a malformed one, please "
            f"open an issue — the limit exists to stop a hostile file, not your work."
        )


def check_page_count(pages: int, limits: Limits = DEFAULT_LIMITS) -> None:
    """Refuse a document claiming more pages than we are willing to handle."""
    if pages > limits.max_pages:
        raise LimitExceededError(
            f"this document reports {pages:,} pages, above the {limits.max_pages:,} page limit"
        )


def _human(count: int) -> str:
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"
