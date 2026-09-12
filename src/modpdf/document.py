"""Opening and saving PDFs.

Every operation goes through this module rather than calling pikepdf directly,
for two reasons: pikepdf's exceptions are accurate but not written for end
users, and saving needs to be atomic (see `modpdf.security.fs`). Keeping both
concerns here means an operation module can be about the operation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pikepdf

from modpdf.security.fs import atomic_write, resolve_input

__all__ = [
    "DamagedDocumentError",
    "DocumentError",
    "EncryptedDocumentError",
    "carry_metadata",
    "open_pdf",
    "save_pdf",
]


class DocumentError(Exception):
    """A PDF could not be opened or saved."""


class EncryptedDocumentError(DocumentError):
    """The PDF is encrypted and the supplied password was wrong or missing."""


class DamagedDocumentError(DocumentError):
    """The file is not a PDF, or is corrupt beyond what QPDF can recover."""


@contextmanager
def open_pdf(path: Path, *, password: str | None = None) -> Iterator[pikepdf.Pdf]:
    """Open a PDF for reading, closing it again on the way out.

    Args:
        path: The file to open.
        password: The user or owner password, if the document is encrypted.
            Never pass one that came from a command-line argument — see
            `modpdf.security.secrets` for why.

    Raises:
        EncryptedDocumentError: The document is encrypted and we cannot open it.
        DamagedDocument: The file is not a readable PDF.
        FileSystemError: The path is missing, unreadable, or not a regular file.
    """
    resolved = resolve_input(path)

    try:
        pdf = pikepdf.open(resolved, password=password or "")
    except pikepdf.PasswordError:
        detail = "the password is wrong" if password else "it needs a password"
        raise EncryptedDocumentError(
            f"cannot open {path.name}: {detail}. Supply one with --password-stdin."
        ) from None
    except pikepdf.PdfError as exc:
        raise DamagedDocumentError(f"cannot read {path.name} as a PDF: {exc}") from exc

    try:
        yield pdf
    finally:
        pdf.close()


def save_pdf(pdf: pikepdf.Pdf, destination: Path, *, overwrite: bool = False) -> Path:
    """Write a PDF to disk atomically. Returns the path actually written."""
    with atomic_write(destination, overwrite=overwrite) as staged:
        try:
            pdf.save(staged)
        except pikepdf.PdfError as exc:
            raise DocumentError(f"failed to write {destination.name}: {exc}") from exc
    return destination


def carry_metadata(source: pikepdf.Pdf, target: pikepdf.Pdf) -> None:
    """Copy document metadata from one PDF to another.

    We preserve metadata rather than dropping it, which for a privacy-minded
    tool deserves an explanation: this is the user's own document, and silently
    losing its title, author and dates when they only asked to reorder two pages
    would be its own kind of data loss. Stripping metadata is a separate,
    explicit decision, which is what the `sanitize` command is for.

    Both the old-style document info dictionary and the newer XMP stream are
    copied, because readers disagree about which one wins and leaving only one
    behind produces documents whose title depends on who opens them.
    """
    if source.trailer.get("/Info") is not None:
        # copy_foreign is typed as returning the generic Object; across a
        # document boundary a copied /Info dictionary is still a Dictionary.
        target.docinfo = cast(pikepdf.Dictionary, target.copy_foreign(source.docinfo))

    xmp = source.Root.get("/Metadata")
    if xmp is not None:
        target.Root["/Metadata"] = target.copy_foreign(xmp)
