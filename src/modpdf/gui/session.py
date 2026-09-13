"""What the window is currently holding.

A session is the document the user opened plus the edits they have made to it,
which are kept entirely in memory as an ordering of the source document's pages.
Nothing touches the file on disk until Save, and Save is `tasks.extract_pages`
with that ordering — the same call the command line makes for `reorder`.

Keeping edits as an ordering rather than as a modified document is what makes
"revert" free and "nothing is written until you save" true rather than aspirational.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from modpdf import tasks
from modpdf.inspection import Inspection

__all__ = ["Session", "load", "positions_to_groups"]


@dataclass
class Session:
    """An open document and the pending, unwritten changes to it."""

    path: Path
    inspection: Inspection
    password: str | None = None
    order: list[int] = field(default_factory=list)
    repairs: tuple[str, ...] = ()

    @property
    def source_pages(self) -> int:
        """How many pages the file on disk has."""
        return self.inspection.page_count

    @property
    def pages(self) -> int:
        """How many pages the document would have if saved now."""
        return len(self.order)

    @property
    def modified(self) -> bool:
        return self.order != list(range(self.source_pages))

    @property
    def dropped(self) -> int:
        """How many of the original pages would not survive a save."""
        return self.source_pages - len(set(self.order))

    def revert(self) -> None:
        self.order = list(range(self.source_pages))

    def remove(self, positions: Iterable[int]) -> None:
        """Drop pages by their position in the current order."""
        doomed = set(positions)
        remaining = [page for at, page in enumerate(self.order) if at not in doomed]
        if not remaining:
            raise ValueError("a document must keep at least one page")
        self.order = remaining

    def duplicate(self, positions: Iterable[int]) -> None:
        """Insert a copy of each selected page directly after it."""
        chosen = set(positions)
        rebuilt: list[int] = []
        for at, page in enumerate(self.order):
            rebuilt.append(page)
            if at in chosen:
                rebuilt.append(page)
        self.order = rebuilt

    def move(self, positions: Sequence[int], before: int) -> int:
        """Move the pages at `positions` so they land immediately before `before`.

        `before` is an insertion point in the *current* order, counted the way a
        cursor between two pages is: 0 is before the first page, and len(order)
        is after the last. Dragging page 3 into the gap between pages 5 and 6
        gives positions=[2], before=5.

        The moved pages keep their order relative to each other, which is what
        someone dragging a block of four pages means by moving them.

        Returns the position the block landed at, so the caller can leave those
        pages selected where the user dropped them.
        """
        chosen = sorted(set(positions))
        if not chosen:
            return before
        if not 0 <= before <= len(self.order):
            raise ValueError(f"cannot insert at {before}; there are {len(self.order)} pages")
        if chosen[0] < 0 or chosen[-1] >= len(self.order):
            raise ValueError("cannot move a page that is not in the document")

        moving = [self.order[at] for at in chosen]
        staying = [page for at, page in enumerate(self.order) if at not in set(chosen)]
        # Removing the moved pages shifts the insertion point left by however
        # many of them were in front of it.
        landing = before - sum(1 for at in chosen if at < before)
        staying[landing:landing] = moving
        self.order = staying
        return landing

    def reorder(self, order: Sequence[int]) -> None:
        """Replace the ordering wholesale, after a drag in the page grid."""
        if sorted(order) != sorted(self.order):
            raise ValueError("a reorder must keep exactly the same pages")
        self.order = list(order)

    def save_to(self, destination: Path, *, overwrite: bool = False) -> Path:
        """Write the pending ordering out. Runs on a worker thread."""
        return tasks.extract_pages(
            self.path,
            self.order,
            destination,
            password=self.password,
            overwrite=overwrite,
        )


def positions_to_groups(order: Sequence[int], ranges: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Turn 1-based (start, end) position ranges into source-page-index groups.

    Each range is inclusive and 1-based, and counted against the grid's
    current order: "1 to 3" means the first three tiles shown right now,
    whatever original pages they hold.

    A reversed pair is swapped rather than refused. The command line's page
    spec parser treats a backwards range ("5-1") as a mistake worth a warning,
    because typed text is genuinely ambiguous about what was meant; two
    separate Start and End spin boxes carry no such ambiguity; whichever is
    smaller is where the range starts.
    """
    groups: list[list[int]] = []
    for start, end in ranges:
        low, high = min(start, end), max(start, end)
        low = max(low, 1)
        high = min(high, len(order))
        if low > high:
            continue  # entirely outside the document; nothing to include
        groups.append([order[position - 1] for position in range(low, high + 1)])
    return groups


def load(path: Path, password: str | None = None) -> Session:
    """Open a document and read what is in it. Runs on a worker thread.

    Inspecting on open costs one pass over the file and means the window can
    show what the document contains straight away, rather than making the user
    go and ask.
    """
    found = tasks.inspect_file(path, password=password)
    return Session(
        path=path,
        inspection=found,
        password=password,
        order=list(range(found.page_count)),
        repairs=found.repairs,
    )
