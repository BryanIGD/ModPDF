"""Whole operations, as both interfaces perform them.

Each function here is one complete job: open the document, do the work, write
the result. They are the seam between what ModPDF does and how it is asked —
the command line and the desktop app call exactly these, so a fix to either
reaches both, and neither can reach the filesystem without going through the
security layer these functions use.

Passwords are taken, never asked for. Prompting is an interface decision — a
terminal reads stdin, a window opens a dialog — so these raise
`EncryptedDocumentError` and let the caller decide how to ask and retry.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

from modpdf.document import open_pdf, save_pdf
from modpdf.inspection import Inspection, count_revisions, inspect_document
from modpdf.ops import compress as compress_module
from modpdf.ops.compress import CompressReport, Mode
from modpdf.ops.merge import merge_documents
from modpdf.ops.sanitize import SanitizeReport, sanitize
from modpdf.ops.select import select_pages
from modpdf.ops.split import Piece
from modpdf.security.fs import resolve_input

__all__ = [
    "DamageReport",
    "append_document",
    "compress_file",
    "extract_pages",
    "inspect_file",
    "merge_files",
    "page_count",
    "sanitize_file",
    "split_document",
]

# Called with every repair QPDF had to make, when a file turns out to be damaged.
DamageReport = Callable[[list[str]], None]


def page_count(source: Path, *, password: str | None = None) -> int:
    """How many pages a document has.

    Split and reorder need this before they can work out which pages to take,
    so the command line opens the file once for this and once to do the job.
    Opening a PDF reads its cross-reference table, not its content, so the
    second open is cheap even on a very large file — cheap enough that it is
    not worth complicating every caller to avoid it.
    """
    with open_pdf(source, password=password) as pdf:
        return len(pdf.pages)


def extract_pages(
    source: Path,
    order: Sequence[int],
    destination: Path,
    *,
    password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> Path:
    """Write the given pages, in the given order, to a new file.

    This one function covers reordering, extracting a selection, deleting pages
    (by leaving them out) and duplicating them (by repeating an index), because
    all four are the same operation seen from different angles.
    """
    with open_pdf(source, password=password, on_damage=on_damage) as pdf:
        return save_pdf(select_pages(pdf, order), destination, overwrite=overwrite)


def split_document(
    source: Path,
    pieces: Sequence[Piece],
    output_dir: Path,
    *,
    password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> list[Path]:
    """Write each piece as its own file. Returns the paths written, in order."""
    target = output_dir.expanduser()
    # 0700: a folder about to hold pieces of a confidential document should not
    # be readable by other accounts on the machine.
    target.mkdir(parents=True, exist_ok=True, mode=0o700)

    written: list[Path] = []
    with open_pdf(source, password=password, on_damage=on_damage) as pdf:
        for piece in pieces:
            written.append(
                save_pdf(
                    select_pages(pdf, piece.indices),
                    target / piece.filename,
                    overwrite=overwrite,
                )
            )
    return written


def merge_files(
    sources: Sequence[Path],
    destination: Path,
    *,
    password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> tuple[Path, list[int]]:
    """Join documents in the order given. Returns the path and each input's page count.

    One password is applied to every input. Documents with different passwords
    are rare enough that asking for one per file would cost every other user
    something, and nobody has asked for it yet.
    """
    if len(sources) < 2:
        raise ValueError("merging needs at least two files")

    with ExitStack() as stack:
        documents = [
            stack.enter_context(open_pdf(path, password=password, on_damage=on_damage))
            for path in sources
        ]
        counts = [len(pdf.pages) for pdf in documents]
        written = save_pdf(merge_documents(documents), destination, overwrite=overwrite)
    return written, counts


def append_document(
    base: Path,
    base_order: Sequence[int],
    addition: Path,
    destination: Path,
    *,
    password: str | None = None,
    addition_password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> tuple[Path, int]:
    """Add another document's pages onto the end of a working order.

    This is what the desktop app's Open button calls when a document is
    already open, to build a workspace out of more than one file.
    `base_order` is honoured exactly as given — including any reordering,
    deletion or duplication already pending on `base` — rather than
    reopening `base` fresh and starting from its original page order.
    Discarding pending edits the moment a second file is added would silently
    undo whatever editing came before it, which is worse than the one extra
    file this opens.

    One password unlocks `base`; `addition` may need a different one, so it
    takes its own rather than reusing `password`.
    """
    with ExitStack() as stack:
        base_pdf = stack.enter_context(open_pdf(base, password=password, on_damage=on_damage))
        addition_pdf = stack.enter_context(
            open_pdf(addition, password=addition_password, on_damage=on_damage)
        )
        ordered_base = select_pages(base_pdf, base_order)
        added_pages = len(addition_pdf.pages)
        combined = merge_documents([ordered_base, addition_pdf])
        written = save_pdf(combined, destination, overwrite=overwrite)
    return written, added_pages


def sanitize_file(
    source: Path,
    destination: Path,
    *,
    keep_metadata: bool = False,
    strip_links: bool = False,
    password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> tuple[Path, SanitizeReport]:
    """Write a cleaned copy, and report what was taken out of it."""
    resolved = resolve_input(source)
    revisions = count_revisions(resolved.read_bytes())

    with open_pdf(resolved, password=password, on_damage=on_damage) as pdf:
        cleaned, report = sanitize(
            pdf,
            keep_metadata=keep_metadata,
            strip_links=strip_links,
            revisions=revisions,
        )
        written = save_pdf(cleaned, destination, overwrite=overwrite)
    return written, report


def inspect_file(source: Path, *, password: str | None = None) -> Inspection:
    """Report what is inside a document. Reads only; changes nothing."""
    return inspect_document(source, password=password)


def compress_file(
    source: Path,
    destination: Path,
    *,
    mode: Mode = "visual",
    target_dpi: int = compress_module.DEFAULT_TARGET_DPI,
    verify: bool = True,
    password: str | None = None,
    overwrite: bool = False,
    on_damage: DamageReport | None = None,
) -> tuple[Path, CompressReport]:
    """Write a smaller copy, and report where the savings came from.

    `before_bytes` — the number every other figure in the report is measured
    against — comes from the real file on disk, not a re-serialization of it;
    see `modpdf.ops.compress.compress` for why that distinction is the
    caller's to make. The file is saved with the same structural options used
    to produce that report, so the number it prints is the number that lands
    on disk.
    """
    before_bytes = resolve_input(source).stat().st_size

    with open_pdf(source, password=password, on_damage=on_damage) as pdf:
        compressed, report = compress_module.compress(
            pdf,
            before_bytes=before_bytes,
            mode=mode,
            target_dpi=target_dpi,
            verify=verify,
        )
        written = save_pdf(
            compressed, destination, overwrite=overwrite, **compress_module.STRUCTURAL_SAVE_OPTIONS
        )
    return written, report
