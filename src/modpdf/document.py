"""Opening and saving PDFs.

Every operation goes through this module rather than calling pikepdf directly,
for two reasons: pikepdf's exceptions are accurate but not written for end
users, and saving needs to be atomic (see `modpdf.security.fs`). Keeping both
concerns here means an operation module can be about the operation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pikepdf

from modpdf.security.fs import atomic_write, resolve_input
from modpdf.security.limits import DEFAULT_LIMITS, Limits, check_file_size, check_page_count

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
def open_pdf(
    path: Path,
    *,
    password: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
    on_damage: Callable[[list[str]], None] | None = None,
) -> Iterator[pikepdf.Pdf]:
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
    check_file_size(resolved, limits)

    try:
        pdf = pikepdf.open(resolved, password=password or "")
    except pikepdf.PasswordError:
        # Only suggest how to supply a password when one was not already tried.
        if password:
            message = f"cannot open {path.name}: the password is wrong"
        else:
            message = (
                f"cannot open {path.name}: it is encrypted and needs a password. "
                f"Supply one with --password-stdin or the MODPDF_PASSWORD variable."
            )
        raise EncryptedDocumentError(message) from None
    except pikepdf.PdfError as exc:
        raise DamagedDocumentError(f"cannot read {path.name} as a PDF: {exc}") from exc
    except OSError as exc:
        # QPDF reports some malformed files through errno rather than its own
        # exception type — a bare "%PDF-" header with nothing after it arrives
        # as EINVAL. Without this, a crafted file gets a traceback instead of
        # an error message.
        raise DamagedDocumentError(f"cannot read {path.name} as a PDF: {exc.strerror}") from exc

    try:
        check_page_count(len(pdf.pages), limits)
        if on_damage is not None:
            repairs = [_repair_message(warning, resolved) for warning in pdf.get_warnings()]
            if repairs:
                on_damage(repairs)
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


def _repair_message(warning: object, path: Path) -> str:
    """Tidy one QPDF warning for display.

    QPDF prefixes every warning with the full path of the file, which is both
    noisy when several are printed together and an unnecessary way to spill a
    filesystem path into terminal output.
    """
    text = str(warning)
    for prefix in (str(path), path.name):
        if not text.startswith(prefix):
            continue
        # QPDF writes either "<path>: message" or, when it can place the fault,
        # "<path> (object 16 0, offset 2749): message". The object context is
        # worth keeping; the path is not.
        text = text[len(prefix) :].lstrip()
        if text.startswith(":"):
            text = text[1:].lstrip()
        return text
    return text
