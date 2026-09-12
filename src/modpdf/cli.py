"""The `modpdf` command line.

This layer does three things and nothing else: turn arguments into the values
the operations want, call them, and report what happened. Any logic that a
future GUI would also need belongs in `modpdf.ops`, not here.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from modpdf import __version__
from modpdf.document import DocumentError, open_pdf, save_pdf
from modpdf.ops.merge import merge_documents
from modpdf.ops.select import select_pages
from modpdf.ops.split import Piece, chunks, plan_pieces
from modpdf.pagespec import PageSpecError, parse_pagespec, parse_pagespec_groups
from modpdf.security.fs import FileSystemError

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
USER_ERRORS = (PageSpecError, DocumentError, FileSystemError, ValueError, IndexError)


@contextmanager
def reporting() -> Iterator[None]:
    try:
        yield
    except USER_ERRORS as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from None


def read_password(from_stdin: bool) -> str | None:
    """Read a password from stdin.

    There is deliberately no --password option that takes the password as an
    argument. Command-line arguments are visible to every other process on the
    machine through `ps`, so a flag like that hands the key to a document to
    anyone with a shell on the same box.
    """
    if not from_stdin:
        return None
    return sys.stdin.readline().rstrip("\n")


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

        with open_pdf(source, password=read_password(password_stdin)) as pdf:
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
) -> None:
    """Join several PDFs into one, in the order given."""
    with reporting():
        if len(sources) < 2:
            raise ValueError("merging needs at least two files")

        with ExitStack() as stack:
            opened = [stack.enter_context(open_pdf(path)) for path in sources]
            counts = " + ".join(str(len(pdf.pages)) for pdf in opened)
            merged = merge_documents(opened)
            total = len(merged.pages)
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
        with open_pdf(source, password=read_password(password_stdin)) as pdf:
            original = len(pdf.pages)
            indices = parse_pagespec(order, original)
            save_pdf(select_pages(pdf, indices), output, overwrite=force)

        dropped = original - len(set(indices))
        note = f" [yellow]({dropped} pages dropped)[/yellow]" if dropped else ""
        out.print(f"{original} pages → {output} [dim]{len(indices)} pages[/dim]{note}")


def _preview(pieces: list[Piece], output_dir: Path, page_count: int) -> None:
    out.print("[dim]dry run — nothing written[/dim]")
    out.print(f"{page_count} pages → {len(pieces)} files in {output_dir}")
    for piece in pieces:
        first, last = piece.indices[0] + 1, piece.indices[-1] + 1
        span = f"page {first}" if first == last else f"pages {first}-{last}"
        out.print(f"  {piece.filename}  [dim]{span}[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
