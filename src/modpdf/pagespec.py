"""Parsing for page specifications like ``1-5,8,12-``.

Page numbers here mean what a person means by a page number: they start at 1 and
ranges include both ends, exactly like the page box in a print dialog. Negative
numbers count back from the end, so ``-1`` is the last page.

Everywhere else in this codebase pages are 0-based indices, because that is what
pikepdf uses. Converting at this boundary and nowhere else is deliberate: it
keeps every off-by-one error that this project will ever have inside one file
with one test module pointed at it.
"""

from __future__ import annotations

import re

__all__ = ["PageSpecError", "parse_pagespec", "parse_pagespec_groups"]

# A leading "-" always introduces a negative page number, never an open-ended
# range. That is why there is no "-5 means pages 1 to 5" syntax: allowing it
# would make "-5" ambiguous, and silently picking the wrong meaning of a page
# range is the kind of bug that quietly hands someone the wrong document.
_SINGLE = re.compile(r"^(-?\d+)$")
_RANGE = re.compile(r"^(-?\d+)-(-?\d+)?$")


class PageSpecError(ValueError):
    """A page spec could not be parsed, or names pages the document does not have."""


def parse_pagespec(spec: str, page_count: int) -> list[int]:
    """Turn a page spec into 0-based page indices.

    Order is preserved and duplicates are kept, because both carry meaning:
    ``3,1,2`` is a reordering and ``1,1,2`` legitimately repeats a page.

    Args:
        spec: The specification, for example ``"1-3,7,12-"`` or ``"-1"``.
        page_count: How many pages the document actually has.

    Returns:
        0-based indices, in the order the spec listed them.

    Raises:
        PageSpecError: The spec is malformed or refers to a page out of range.
    """
    return [index for group in parse_pagespec_groups(spec, page_count) for index in group]


def parse_pagespec_groups(spec: str, page_count: int) -> list[list[int]]:
    """Parse a page spec, keeping each comma-separated part as its own group.

    ``split`` needs this: in ``1-3,7,12-`` the commas are not decoration, they
    are where one output file ends and the next begins. Everything else wants
    the flattened form from `parse_pagespec`.
    """
    if page_count < 1:
        raise PageSpecError("the document has no pages")

    cleaned = spec.strip()
    if not cleaned:
        raise PageSpecError("empty page spec")

    groups: list[list[int]] = []
    for raw_part in cleaned.split(","):
        part = raw_part.strip()
        if not part:
            raise PageSpecError(f"empty range in {spec!r} — check for a stray comma")
        groups.append(_parse_part(part, page_count))
    return groups


def _parse_part(part: str, page_count: int) -> list[int]:
    if match := _SINGLE.match(part):
        return [_resolve(int(match.group(1)), page_count, part)]

    if match := _RANGE.match(part):
        start = _resolve(int(match.group(1)), page_count, part)
        end_text = match.group(2)
        end = _resolve(int(end_text), page_count, part) if end_text else page_count - 1
        if start > end:
            raise PageSpecError(
                f"{part!r} runs backwards; ranges go low to high, so you probably "
                f"meant {end + 1}-{start + 1}"
            )
        return list(range(start, end + 1))

    raise PageSpecError(
        f"could not understand {part!r}. Page specs look like '1-5', '8', '12-' or "
        f"'-1' for the last page, joined with commas."
    )


def _resolve(number: int, page_count: int, part: str) -> int:
    """Convert one 1-based (or negative) page number to a 0-based index."""
    if number == 0:
        raise PageSpecError(f"{part!r} refers to page 0, but pages are numbered from 1")

    index = number - 1 if number > 0 else page_count + number
    if not 0 <= index < page_count:
        pages = "page" if page_count == 1 else "pages"
        raise PageSpecError(
            f"{part!r} refers to page {number}, but the document has {page_count} {pages}"
        )
    return index
