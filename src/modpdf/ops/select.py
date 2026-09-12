"""Building a new document from a chosen sequence of pages.

Split and reorder are the same operation wearing different hats. Both pick page
indices and both produce a document containing exactly those pages in exactly
that order; reorder happens to pick all of them, and split happens to do it
several times. Writing it once means there is one place where page identity can
go wrong, and one set of tests watching it.
"""

from __future__ import annotations

from collections.abc import Sequence

import pikepdf

from modpdf.document import carry_metadata
from modpdf.ops.outline import copy_outline, page_mapping

__all__ = ["select_pages"]


def select_pages(source: pikepdf.Pdf, indices: Sequence[int]) -> pikepdf.Pdf:
    """Return a new document holding ``source``'s pages in the order given.

    Indices are 0-based (``modpdf.pagespec`` converts from human page numbers).
    Repeats are allowed and duplicate the page, which is a legitimate thing to
    want. The source document is not modified.

    Bookmarks are rebuilt against the new page order; see `modpdf.ops.outline`.

    Raises:
        IndexError: An index does not exist in the source document.
    """
    if not indices:
        raise ValueError("no pages selected")

    page_count = len(source.pages)
    for index in indices:
        if not 0 <= index < page_count:
            raise IndexError(f"page index {index} is outside the document's {page_count} pages")

    result = pikepdf.Pdf.new()
    for index in indices:
        result.pages.append(source.pages[index])
    carry_metadata(source, result)
    copy_outline(source, result, page_mapping(indices))
    return result
