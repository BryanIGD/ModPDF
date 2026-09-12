"""Joining several PDFs into one."""

from __future__ import annotations

from collections.abc import Sequence

import pikepdf

from modpdf.document import carry_metadata
from modpdf.ops.outline import copy_outline

__all__ = ["merge_documents"]


def merge_documents(sources: Sequence[pikepdf.Pdf]) -> pikepdf.Pdf:
    """Concatenate documents in the order given.

    Each document's bookmarks are carried over and shifted into position, so
    the merged outline reads top to bottom in the order the files were given.

    Metadata is taken from the first document. There is no correct answer to
    whose title a merged document should carry, and every alternative we
    considered was worse: inventing a new title guesses, and dropping metadata
    loses information the user never asked to lose. Taking the first is at least
    predictable, and it is what the user usually means by the first file they
    typed.

    Raises:
        ValueError: Fewer than two documents were given.
    """
    if len(sources) < 2:
        raise ValueError("merging needs at least two documents")

    result = pikepdf.Pdf.new()
    offset = 0
    for source in sources:
        result.pages.extend(source.pages)
        # Each document's bookmarks are shifted by the pages already placed, so
        # the merged outline reads as one document in the order given.
        shifted = {index: index + offset for index in range(len(source.pages))}
        copy_outline(source, result, shifted)
        offset += len(source.pages)

    carry_metadata(sources[0], result)
    return result
