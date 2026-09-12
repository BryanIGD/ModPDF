"""Carrying bookmarks across an operation.

A bookmark is a title plus a pointer to a page. Rearranging pages invalidates
every one of those pointers, so an operation that copies pages and ignores the
outline produces a document whose table of contents silently sends the reader to
the wrong place — or, as pikepdf does by default, drops the outline entirely.
Either way a three-hundred-page report loses the only practical way to navigate
it, and the user is not told.

So we rebuild the outline against the new page order, keep every entry whose
page survived, and drop the ones whose page did not. Entries whose page was
removed but whose children survived are promoted rather than discarded, because
losing a whole chapter's worth of bookmarks over a missing chapter heading is
not what anyone means by splitting a document.

The outline keeps its original shape and order. After a reversal the bookmarks
still read Chapter 1, Chapter 2, Chapter 3 even though the pages now run the
other way. Sorting them by page instead would be well defined only for a flat
outline: once entries are nested, a child can precede its own parent, and there
is no ordering that is both sorted and still a tree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pikepdf
from pikepdf import OutlineItem

__all__ = ["OutlineResult", "copy_outline", "page_mapping"]


@dataclass(frozen=True)
class OutlineResult:
    """How the outline fared. Counts entries at every depth, not just the top."""

    kept: int
    dropped: int

    @property
    def had_outline(self) -> bool:
        return bool(self.kept or self.dropped)


def page_mapping(indices: Sequence[int]) -> dict[int, int]:
    """Map each source page index to where it now lives.

    When a page appears more than once — ``--order 1,1,2`` is legal — its
    bookmarks point at the first copy. Pointing at all of them would duplicate
    every bookmark, which is worse.
    """
    mapping: dict[int, int] = {}
    for new_index, source_index in enumerate(indices):
        mapping.setdefault(source_index, new_index)
    return mapping


def copy_outline(
    source: pikepdf.Pdf,
    target: pikepdf.Pdf,
    mapping: Mapping[int, int],
) -> OutlineResult:
    """Rebuild ``source``'s outline inside ``target``, following ``mapping``.

    Appends to any outline the target already has, so merge can call this once
    per input document and get the sections in order.
    """
    names = _named_destinations(source)

    with source.open_outline() as source_outline:
        rebuilt, kept, dropped = _rebuild(source_outline.root, source, mapping, names)

    if rebuilt:
        with target.open_outline() as target_outline:
            target_outline.root.extend(rebuilt)

    return OutlineResult(kept=kept, dropped=dropped)


def _rebuild(
    items: Sequence[OutlineItem],
    source: pikepdf.Pdf,
    mapping: Mapping[int, int],
    names: Mapping[str, pikepdf.Object],
) -> tuple[list[OutlineItem], int, int]:
    kept_items: list[OutlineItem] = []
    kept = 0
    dropped = 0

    for item in items:
        children, child_kept, child_dropped = _rebuild(item.children, source, mapping, names)
        kept += child_kept
        dropped += child_dropped

        source_page = _target_page(item, source, names)
        new_page = mapping.get(source_page) if source_page is not None else None

        if new_page is None:
            # This entry's page is gone. Its surviving children are promoted to
            # take its place rather than disappearing with it.
            dropped += 1
            kept_items.extend(children)
            continue

        rebuilt = OutlineItem(item.title, new_page)
        rebuilt.children.extend(children)
        kept_items.append(rebuilt)
        kept += 1

    return kept_items, kept, dropped


def _target_page(
    item: OutlineItem,
    source: pikepdf.Pdf,
    names: Mapping[str, pikepdf.Object],
) -> int | None:
    """Which page of ``source`` this bookmark points at, if we can tell."""
    # Deliberately Any: a destination is walked through several PDF shapes
    # (name, dictionary, array) that pikepdf's annotations model as distinct
    # types but that are one dynamically-typed object at runtime.
    destination: Any = item.destination

    # A bookmark may carry its target directly, or wrap it in a GoTo action.
    if destination is None and item.action is not None:
        action = item.action
        if action.get("/S") == pikepdf.Name("/GoTo"):
            destination = action.get("/D")

    if destination is None:
        return None

    # Named destinations are an indirection through the document's name tree.
    if isinstance(destination, pikepdf.String | pikepdf.Name):
        resolved = names.get(_destination_key(destination))
        if resolved is None:
            return None
        destination = resolved

    if isinstance(destination, pikepdf.Dictionary):
        destination = destination.get("/D")

    if not isinstance(destination, pikepdf.Array) or len(destination) == 0:
        return None

    # The isinstance check above narrows destination to an Array, whose items
    # pikepdf types as Object; the first item of a destination array is a page.
    page: Any = destination[0]
    try:
        return source.pages.index(page)
    except (ValueError, TypeError):
        # The bookmark points somewhere that is not a page of this document.
        return None


def _named_destinations(pdf: pikepdf.Pdf) -> dict[str, pikepdf.Object]:
    """Collect the document's named destinations from both places they can live.

    PDF 1.1 put them in a ``/Dests`` dictionary; PDF 1.2 moved them to a name
    tree under ``/Names``. Real files use either, and LaTeX and InDesign output
    leans heavily on named destinations, so ignoring them would mean losing the
    bookmarks in a large share of the documents people actually have.
    """
    collected: dict[str, pikepdf.Object] = {}
    root = pdf.Root

    legacy = root.get("/Dests")
    if isinstance(legacy, pikepdf.Dictionary):
        for key, value in legacy.items():
            collected[_destination_key(key)] = value

    names = root.get("/Names")
    if isinstance(names, pikepdf.Dictionary):
        tree = names.get("/Dests")
        if tree is not None:
            try:
                for tree_key, tree_value in pikepdf.NameTree(tree).items():
                    collected[_destination_key(tree_key)] = tree_value
            except (TypeError, ValueError):
                pass

    return collected


def _destination_key(value: object) -> str:
    """Normalise a destination name for lookup.

    The same destination is spelled two ways depending on where it appears: a
    ``/Dests`` dictionary uses PDF names, which carry a leading slash, while a
    name tree uses strings, which do not. Stripping it on both sides is what
    makes a bookmark written as ``/sec1`` find a destination stored as ``sec1``.
    """
    return str(value).lstrip("/")
