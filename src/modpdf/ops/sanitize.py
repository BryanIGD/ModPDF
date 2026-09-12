"""Removing everything in a PDF that is not the document.

A PDF can carry code, automatic actions, hidden attachments and earlier drafts
of itself. `sanitize` strips all of that and leaves the pages.

The method is to rebuild rather than to edit. Deleting a reference to a piece of
JavaScript leaves the JavaScript sitting in the file, unreferenced but entirely
recoverable, which is not what anyone means by removing it. So we construct a
new document and copy the pages across; anything the pages do not reach — the
catalog's OpenAction, the document JavaScript tree, embedded file attachments,
the XFA form, and every earlier revision the file had accumulated — is simply
never copied, and its bytes do not exist in the output. What the pages *do*
carry with them, their annotations, is then cleaned in place.

One deliberate distinction. Actions that fire on their own or execute code —
JavaScript, Launch, SubmitForm, ImportData, GoToR — are removed, because
nothing in a document should be able to run without being asked. Plain web
links are kept, because a citation in a report is content, and a reader has to
click it. `--strip-links` removes those too for anyone who wants no outbound
references at all.

This is not redaction. Sanitizing removes machinery, not information: text that
is on a page stays on that page, and anything blacked out with a rectangle is
still underneath. See the README on why redaction is not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pikepdf

from modpdf.inspection import scan_objects
from modpdf.ops.select import select_pages

__all__ = ["ACTIONS_THAT_RUN_THEMSELVES", "SanitizeReport", "sanitize"]

# Actions a document can perform without the reader choosing to.
ACTIONS_THAT_RUN_THEMSELVES = frozenset(
    {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToR", "/Movie", "/Sound"}
)

# Actions that need a deliberate click. Kept unless --strip-links is given.
ACTIONS_THE_READER_CHOOSES = frozenset({"/URI"})


@dataclass(frozen=True)
class SanitizeReport:
    """What was taken out, so the user can see the command did something."""

    javascript: int = 0
    actions_removed: dict[str, int] = field(default_factory=dict)
    embedded_files: int = 0
    xfa: bool = False
    open_action: bool = False
    annotations_cleaned: int = 0
    page_actions_removed: int = 0
    metadata_stripped: bool = False
    revisions_collapsed: int = 0

    @property
    def anything_removed(self) -> bool:
        return bool(
            self.javascript
            or self.actions_removed
            or self.embedded_files
            or self.xfa
            or self.open_action
            or self.annotations_cleaned
            or self.page_actions_removed
            or self.metadata_stripped
            or self.revisions_collapsed
        )


def sanitize(
    source: pikepdf.Pdf,
    *,
    keep_metadata: bool = False,
    strip_links: bool = False,
    revisions: int = 1,
) -> tuple[pikepdf.Pdf, SanitizeReport]:
    """Return a cleaned copy of ``source`` and a report of what was removed.

    Args:
        source: The document to clean. Not modified.
        keep_metadata: Keep the title, author and dates. Off by default: someone
            running `sanitize` is usually about to send the file to someone else.
        strip_links: Also remove plain web links, not just automatic actions.
        revisions: How many revisions the file had, from `inspect`. Used only to
            report how many were collapsed; rebuilding always leaves exactly one.

    Raises:
        ValueError: The document has no pages.
    """
    if len(source.pages) == 0:
        raise ValueError("the document has no pages")

    census = scan_objects(source)
    open_action = "/OpenAction" in source.Root
    xfa = _has_xfa(source)

    # Everything not reachable from a page is dropped by being left behind.
    result = select_pages(source, list(range(len(source.pages))))

    annotations_cleaned, page_actions, removed_by_type = _clean_pages(
        result, strip_links=strip_links
    )

    metadata_stripped = False
    if not keep_metadata:
        metadata_stripped = _strip_metadata(result)

    return result, SanitizeReport(
        javascript=int(census["javascript"]),
        actions_removed=removed_by_type,
        embedded_files=len(census["embedded_files"]),
        xfa=xfa,
        open_action=open_action,
        annotations_cleaned=annotations_cleaned,
        page_actions_removed=page_actions,
        metadata_stripped=metadata_stripped,
        revisions_collapsed=max(revisions - 1, 0),
    )


def _clean_pages(pdf: pikepdf.Pdf, *, strip_links: bool) -> tuple[int, int, dict[str, int]]:
    """Strip active content from pages and their annotations, in place.

    Annotations travel with the pages they are attached to, so this is where a
    Launch action or a tracking link survives the rebuild and has to be removed
    explicitly.
    """
    unwanted = set(ACTIONS_THAT_RUN_THEMSELVES)
    if strip_links:
        unwanted |= ACTIONS_THE_READER_CHOOSES

    annotations_cleaned = 0
    page_actions = 0
    removed: dict[str, int] = {}

    for page in pdf.pages:
        obj = page.obj

        # Page-level additional actions: open, close, print. Never legitimate
        # in a document someone is merely reading.
        if "/AA" in obj:
            del obj["/AA"]
            page_actions += 1

        annotations = obj.get("/Annots")
        if not isinstance(annotations, pikepdf.Array):
            continue

        for annotation in annotations:
            if not isinstance(annotation, pikepdf.Dictionary):
                continue
            if _clean_annotation(annotation, unwanted, removed):
                annotations_cleaned += 1

    return annotations_cleaned, page_actions, removed


def _clean_annotation(
    annotation: pikepdf.Dictionary,
    unwanted: set[str],
    removed: dict[str, int],
) -> bool:
    """Remove active content from one annotation. True if anything changed."""
    changed = False

    action = annotation.get("/A")
    if isinstance(action, pikepdf.Dictionary):
        kind = str(action.get("/S", ""))
        if kind in unwanted:
            del annotation["/A"]
            removed[kind] = removed.get(kind, 0) + 1
            changed = True

    # Trigger actions: on focus, on mouse-up, on page open.
    if "/AA" in annotation:
        del annotation["/AA"]
        changed = True

    # A file attachment annotation carries its payload in /FS -> /EF.
    spec = annotation.get("/FS")
    if isinstance(spec, pikepdf.Dictionary) and "/EF" in spec:
        del spec["/EF"]
        removed["/EmbeddedFile"] = removed.get("/EmbeddedFile", 0) + 1
        changed = True

    return changed


def _strip_metadata(pdf: pikepdf.Pdf) -> bool:
    """Remove the document info dictionary and the XMP stream. True if either existed."""
    removed = False

    if pdf.trailer.get("/Info") is not None:
        del pdf.trailer["/Info"]
        removed = True

    if "/Metadata" in pdf.Root:
        del pdf.Root["/Metadata"]
        removed = True

    return removed


def _has_xfa(pdf: pikepdf.Pdf) -> bool:
    form: Any = pdf.Root.get("/AcroForm")
    return isinstance(form, pikepdf.Dictionary) and "/XFA" in form
