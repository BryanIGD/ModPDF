"""Splitting one document into several.

Deciding *what* the output files are is separate from writing them, because
that decision is the part worth showing the user before anything touches the
disk. `plan_pieces` produces the answer; `--dry-run` prints it; the CLI then
feeds each piece to `select_pages`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Piece", "plan_pieces"]


@dataclass(frozen=True)
class Piece:
    """One output file: the pages it holds, and what it should be called."""

    indices: tuple[int, ...]
    filename: str

    @property
    def page_count(self) -> int:
        return len(self.indices)


def plan_pieces(stem: str, groups: Sequence[Sequence[int]]) -> list[Piece]:
    """Name each group of pages, producing the list of files a split will write.

    Names carry the page numbers rather than a bare counter — ``report-p004-006.pdf``
    tells you what is in it and ``report-003.pdf`` does not, which matters once
    there are thirty of them in a folder.
    """
    pieces: list[Piece] = []
    used: dict[str, int] = {}

    for group in groups:
        if not group:
            raise ValueError("a split piece would contain no pages")

        base = _base_name(stem, group)
        seen = used.get(base, 0)
        used[base] = seen + 1
        # Identical page selections are legal (--pages 1,1) but cannot share a
        # filename, so later duplicates get a suffix rather than an overwrite.
        filename = f"{base}.pdf" if seen == 0 else f"{base}-{seen + 1}.pdf"
        pieces.append(Piece(indices=tuple(group), filename=filename))

    return pieces


def _base_name(stem: str, group: Sequence[int]) -> str:
    """Page numbers in filenames are 1-based, because a person reads them."""
    first = group[0] + 1
    last = group[-1] + 1
    if first == last:
        return f"{stem}-p{first:03d}"
    if list(group) == list(range(group[0], group[-1] + 1)):
        return f"{stem}-p{first:03d}-{last:03d}"
    # Non-contiguous groups cannot arise from a page spec, where every comma
    # starts a new group, but the function should not lie if one ever does.
    return f"{stem}-p{first:03d}+{len(group)}"
