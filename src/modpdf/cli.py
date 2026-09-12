"""The `modpdf` command line.

This layer does three things and nothing else: turn arguments into the values
the operations want, call them, and report what happened. Any logic that a
future GUI would also need belongs in `modpdf.ops`, not here.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import pikepdf
import typer
from rich.console import Console

from modpdf import __version__
from modpdf.document import DocumentError, EncryptedDocumentError, open_pdf, save_pdf
from modpdf.inspection import Inspection, count_revisions, inspect_document
from modpdf.ops.merge import merge_documents
from modpdf.ops.sanitize import SanitizeReport
from modpdf.ops.sanitize import sanitize as sanitize_document
from modpdf.ops.select import select_pages
from modpdf.ops.split import Piece, chunks, plan_pieces
from modpdf.pagespec import PageSpecError, parse_pagespec, parse_pagespec_groups
from modpdf.security import netguard, secrets
from modpdf.security.fs import FileSystemError, synced_location
from modpdf.security.limits import LimitExceededError

app = typer.Typer(
    name="modpdf",
    help="Split, merge, reorder and compress PDFs on your own machine.",
    no_args_is_help=True,
    add_completion=False,
)

out = Console()
err = Console(stderr=True)

# Everything a user can do wrong, as opposed to everything that can go wrong.
# These get a one-line message; anything else keeps its traceback, because an
# unexpected failure in a tool like this is a bug we want reported in full.
USER_ERRORS = (
    PageSpecError,
    DocumentError,
    FileSystemError,
    LimitExceededError,
    ValueError,
    IndexError,
)


@contextmanager
def reporting() -> Iterator[None]:
    try:
        yield
    except USER_ERRORS as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from None


def damage_reporter(name: str) -> Callable[[list[str]], None]:
    """Tell the user their document was broken and had to be repaired.

    QPDF repairs a damaged PDF quietly and usually does a good job, but a
    recovered file can have lost pages or content. Processing one without
    saying so would mean handing back a document that is subtly not what the
    user thinks it is.
    """

    def report(repairs: list[str]) -> None:
        count = len(repairs)
        err.print(
            f"[yellow]warning:[/yellow] {name} is damaged. It was repaired well "
            f"enough to read, but content may be missing or altered "
            f"({count} issue{'s' if count != 1 else ''})."
        )
        for detail in repairs[:2]:
            err.print(f"  [dim]{detail}[/dim]")
        if count > 2:
            err.print(f"  [dim]...and {count - 2} more[/dim]")

    return report


@contextmanager
def opened(source: Path, *, use_stdin: bool = False) -> Iterator[pikepdf.Pdf]:
    """Open a PDF, asking for a password only if it turns out to need one.

    Trying first and prompting second means an unencrypted document never asks
    anything, and an encrypted one asks once, at the moment it matters.
    """
    password = secrets.resolve(use_stdin=use_stdin)
    on_damage = damage_reporter(source.name)
    try:
        with open_pdf(source, password=password, on_damage=on_damage) as pdf:
            yield pdf
        return
    except EncryptedDocumentError:
        if password is not None:
            raise
        entered = secrets.ask(source.name)
        if entered is None:
            raise

    with open_pdf(source, password=entered, on_damage=on_damage) as pdf:
        yield pdf


def version_callback(requested: bool) -> None:
    if requested:
        out.print(f"modpdf {__version__}")
        raise typer.Exit


@app.callback()
def main_options(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=version_callback, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """ModPDF works entirely offline. It has no network code and blocks its own."""


def warn_if_synced(destination: Path) -> None:
    """Say so if the output is about to land in a cloud-synced folder.

    ModPDF does not upload anything, but a file written into a Dropbox folder is
    uploaded within seconds all the same, and the user has no reason to think
    about that while typing an output path. We still write the file — it is
    their machine and their decision — we just decline to let them believe
    something that is not true. Written to stderr so --json output stays clean.
    """
    found = synced_location(destination)
    if found is None:
        return
    err.print(
        f"[yellow]note:[/yellow] this writes into your {found.service} folder, "
        f"so {found.service} will upload it."
    )


@app.command()
def split(
    source: Annotated[Path, typer.Argument(help="The PDF to split.")],
    output_dir: Annotated[Path, typer.Option("--out", "-o", help="Directory for the pieces.")],
    pages: Annotated[
        str | None,
        typer.Option(
            "--pages",
            help="Page groups; each comma-separated group becomes one file, e.g. 1-3,7,12-",
        ),
    ] = None,
    every: Annotated[
        int | None, typer.Option("--every", help="Split into consecutive runs of this many pages.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be written.")] = False,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the document password from stdin.")
    ] = False,
) -> None:
    """Split one PDF into several."""
    with reporting():
        if (pages is None) == (every is None):
            raise ValueError("choose exactly one of --pages or --every")

        with opened(source, use_stdin=password_stdin) as pdf:
            count = len(pdf.pages)
            groups = (
                parse_pagespec_groups(pages, count) if pages is not None else chunks(count, every)  # type: ignore[arg-type]
            )
            pieces = plan_pieces(source.stem, groups)

            if dry_run:
                _preview(pieces, output_dir, count)
                return

            # 0700: a folder about to hold pieces of a confidential document
            # should not be readable by other accounts on the machine.
            warn_if_synced(output_dir)
            output_dir.expanduser().mkdir(parents=True, exist_ok=True, mode=0o700)

            for piece in pieces:
                save_pdf(
                    select_pages(pdf, piece.indices),
                    output_dir / piece.filename,
                    overwrite=force,
                )

        out.print(f"{count} pages → {len(pieces)} files in {output_dir}")
        for piece in pieces:
            out.print(f"  {piece.filename}  [dim]{piece.page_count} pages[/dim]")


@app.command()
def merge(
    sources: Annotated[list[Path], typer.Argument(help="PDFs to join, in order.")],
    output: Annotated[Path, typer.Option("--out", "-o", help="The merged PDF.")],
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
    password_stdin: Annotated[
        bool,
        typer.Option(
            "--password-stdin",
            help="Read the document password from stdin; used for every input file.",
        ),
    ] = False,
) -> None:
    """Join several PDFs into one, in the order given."""
    with reporting():
        if len(sources) < 2:
            raise ValueError("merging needs at least two files")

        with ExitStack() as stack:
            documents = [
                stack.enter_context(opened(path, use_stdin=password_stdin)) for path in sources
            ]
            counts = " + ".join(str(len(pdf.pages)) for pdf in documents)
            merged = merge_documents(documents)
            total = len(merged.pages)
            warn_if_synced(output)
            save_pdf(merged, output, overwrite=force)

        out.print(f"{len(sources)} files ({counts} pages) → {output} [dim]{total} pages[/dim]")


@app.command()
def reorder(
    source: Annotated[Path, typer.Argument(help="The PDF to reorder.")],
    output: Annotated[Path, typer.Option("--out", "-o", help="The rearranged PDF.")],
    order: Annotated[str, typer.Option("--order", help="The new page order, e.g. 3,1,2,5-8")],
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the document password from stdin.")
    ] = False,
) -> None:
    """Rearrange, select or duplicate pages.

    The output contains exactly the pages listed, in that order, so leaving a
    page out of --order leaves it out of the document.
    """
    with reporting():
        with opened(source, use_stdin=password_stdin) as pdf:
            original = len(pdf.pages)
            indices = parse_pagespec(order, original)
            warn_if_synced(output)
            save_pdf(select_pages(pdf, indices), output, overwrite=force)

        dropped = original - len(set(indices))
        note = f" [yellow]({dropped} pages dropped)[/yellow]" if dropped else ""
        out.print(f"{original} pages → {output} [dim]{len(indices)} pages[/dim]{note}")


@app.command()
def inspect(
    source: Annotated[Path, typer.Argument(help="The PDF to examine.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable output instead.")
    ] = False,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the document password from stdin.")
    ] = False,
) -> None:
    """Report what is actually inside a PDF. Changes nothing.

    Answers the question you should ask before forwarding a document: what is
    in here besides the pages I can see?
    """
    with reporting():
        found = inspect_document(source, password=secrets.resolve(use_stdin=password_stdin))

        if as_json:
            out.print_json(data=_as_dict(found))
            return

        _print_inspection(found)


def _as_dict(found: Inspection) -> dict[str, object]:
    payload = asdict(found)
    payload["path"] = str(found.path)
    payload["concerns"] = [asdict(concern) for concern in found.concerns]
    return payload


def _print_inspection(found: Inspection) -> None:
    encryption = "encrypted" if found.encrypted else "not encrypted"
    out.print(f"[bold]{found.path.name}[/bold]")
    out.print(
        f"  {found.page_count} pages · {_human_size(found.size_bytes)} · "
        f"PDF {found.pdf_version} · {encryption}"
    )

    concerns = found.concerns
    if not concerns:
        out.print("\n  [green]Nothing notable.[/green] No scripts, no embedded files, no")
        out.print("  automatic actions, and only one revision in the file.")
    else:
        count = len(concerns)
        out.print(f"\n  {count} thing{'s' if count != 1 else ''} worth knowing:\n")
        # Wrapped by hand rather than by the console, so continuation lines stay
        # indented under their heading instead of running back to column 0.
        width = max(out.width - 6, 40)
        for concern in concerns:
            heading = f"{concern.label} — {concern.detail}"
            head, *rest = textwrap.wrap(heading, width=width) or [heading]
            out.print(f"  [yellow]{head}[/yellow]")
            for line in rest:
                out.print(f"  [yellow]{line}[/yellow]")
            for line in textwrap.wrap(concern.why, width=width):
                out.print(f"    [dim]{line}[/dim]")

    if found.permissions:
        allowed = sorted(name for name, ok in found.permissions.items() if ok)
        denied = sorted(name for name, ok in found.permissions.items() if not ok)
        out.print("\n  [bold]Permissions[/bold]")
        out.print(
            "  [dim]These are requests, not enforcement. Any reader is free to ignore them,[/dim]"
        )
        out.print("  [dim]and many do.[/dim]")
        for heading, names in (("allowed", allowed), ("denied ", denied)):
            joined = ", ".join(names) or "none"
            wrapped = textwrap.wrap(joined, width=max(out.width - 14, 40))
            out.print(f"    {heading}: {wrapped[0] if wrapped else 'none'}")
            for line in wrapped[1:]:
                out.print(f"             {line}")

    fonts = f"{len(found.fonts)} font{'s' if len(found.fonts) != 1 else ''}"
    images = f"{found.image_count} image{'s' if found.image_count != 1 else ''}"
    out.print(f"\n  [dim]Contents: {images}, {fonts}[/dim]")
    if found.fonts:
        out.print(f"  [dim]Fonts: {', '.join(found.fonts[:6])}[/dim]")


def _human_size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


@app.command()
def sanitize(
    source: Annotated[Path, typer.Argument(help="The PDF to clean.")],
    output: Annotated[Path, typer.Option("--out", "-o", help="The cleaned PDF.")],
    keep_metadata: Annotated[
        bool,
        typer.Option("--keep-metadata", help="Keep the title, author and dates."),
    ] = False,
    strip_links: Annotated[
        bool,
        typer.Option("--strip-links", help="Also remove plain web links, not just actions."),
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the document password from stdin.")
    ] = False,
) -> None:
    """Remove active content, hidden attachments and earlier revisions.

    Keeps the pages and their text. This is not redaction: anything visible on a
    page stays there, and a black rectangle drawn over text does not remove it.
    """
    with reporting():
        revisions = count_revisions(source.expanduser().read_bytes()) if source.exists() else 1

        with opened(source, use_stdin=password_stdin) as pdf:
            cleaned, report = sanitize_document(
                pdf,
                keep_metadata=keep_metadata,
                strip_links=strip_links,
                revisions=revisions,
            )
            pages = len(cleaned.pages)
            warn_if_synced(output)
            save_pdf(cleaned, output, overwrite=force)

        _print_sanitize_report(report, output, pages)


def _print_sanitize_report(report: SanitizeReport, output: Path, pages: int) -> None:
    out.print(f"{output} [dim]{pages} pages[/dim]")

    if not report.anything_removed:
        out.print("  [green]nothing to remove[/green] — this document was already clean")
        return

    lines: list[str] = []
    if report.javascript:
        lines.append(f"JavaScript ({report.javascript})")
    if report.open_action:
        lines.append("automatic open action")
    for kind, count in sorted(report.actions_removed.items()):
        lines.append(f"{kind.lstrip('/')} actions ({count})")
    if report.page_actions_removed:
        lines.append(f"page trigger actions ({report.page_actions_removed})")
    if report.embedded_files:
        lines.append(f"embedded files ({report.embedded_files})")
    if report.xfa:
        lines.append("XFA form")
    if report.revisions_collapsed:
        lines.append(f"earlier revisions ({report.revisions_collapsed})")
    if report.metadata_stripped:
        lines.append("metadata")

    out.print("  removed: " + ", ".join(lines))
    out.print("  [dim]Pages and text are unchanged. This is not redaction:[/dim]")
    out.print("  [dim]anything visible on a page is still there.[/dim]")


def _preview(pieces: list[Piece], output_dir: Path, page_count: int) -> None:
    out.print("[dim]dry run — nothing written[/dim]")
    out.print(f"{page_count} pages → {len(pieces)} files in {output_dir}")
    for piece in pieces:
        first, last = piece.indices[0] + 1, piece.indices[-1] + 1
        span = f"page {first}" if first == last else f"pages {first}-{last}"
        out.print(f"  {piece.filename}  [dim]{span}[/dim]")


def main() -> None:
    # Before anything is parsed and before any file is opened, take away this
    # process's ability to reach the network. There is deliberately no flag to
    # skip this; see modpdf.security.netguard for what it does and does not buy.
    netguard.install()
    app()


if __name__ == "__main__":
    main()
