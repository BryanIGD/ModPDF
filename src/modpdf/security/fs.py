"""Filesystem handling for a tool that works on confidential documents.

Two rules drive everything here.

First, a document is never half-written. Every output goes to a temporary file
beside its destination, is flushed to disk, and is then moved into place with an
atomic rename. If ModPDF crashes, is killed, or hits a malformed page halfway
through, the destination either does not exist or is complete. There is no state
where the user is holding a truncated PDF that looks plausible.

Second, intermediate files are never readable by anyone else. They are created
with mode 0600 in the destination directory rather than in a shared temporary
directory, which also guarantees the final rename stays on one filesystem and so
really is atomic.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ["FileSystemError", "atomic_write", "resolve_input"]


class FileSystemError(Exception):
    """An input could not be read, or an output could not be safely written."""


def resolve_input(path: Path) -> Path:
    """Check that a path is a readable regular file and return it fully resolved.

    Symlinks are followed deliberately: if the user points us at a link to their
    document, they mean the document. What we refuse is anything that is not a
    regular file, because opening a fifo or a device node and calling it a PDF
    leads somewhere unpleasant.
    """
    expanded = path.expanduser()
    try:
        resolved = expanded.resolve(strict=True)
    except FileNotFoundError:
        raise FileSystemError(f"no such file: {expanded}") from None
    except OSError as exc:
        raise FileSystemError(f"cannot read {expanded}: {exc.strerror}") from exc

    if resolved.is_dir():
        raise FileSystemError(f"{expanded} is a directory, not a PDF")
    if not resolved.is_file():
        raise FileSystemError(f"{expanded} is not a regular file")
    if not os.access(resolved, os.R_OK):
        raise FileSystemError(f"no permission to read {expanded}")
    return resolved


@contextmanager
def atomic_write(destination: Path, *, overwrite: bool = False) -> Iterator[Path]:
    """Yield a temporary path to write to; move it into place on clean exit.

    Use it like this::

        with atomic_write(out) as staged:
            pdf.save(staged)

    If the body raises, the temporary file is removed and the destination is
    left exactly as it was.
    """
    target = destination.expanduser()
    parent = target.parent

    if not parent.is_dir():
        raise FileSystemError(f"the directory {parent} does not exist")
    if not os.access(parent, os.W_OK):
        raise FileSystemError(f"no permission to write in {parent}")
    if target.exists() and not overwrite:
        raise FileSystemError(f"{target} already exists (pass --force to overwrite)")

    # mkstemp creates with mode 0600 and O_EXCL, in the destination directory so
    # the rename below cannot cross a filesystem boundary.
    handle, staged_name = tempfile.mkstemp(dir=parent, prefix=f".{target.name}.", suffix=".part")
    os.close(handle)
    staged = Path(staged_name)

    try:
        yield staged
        if not staged.exists():
            raise FileSystemError("nothing was written to the staged file")
        _flush_to_disk(staged)
        staged.replace(target)
        _flush_directory(parent)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _flush_to_disk(path: Path) -> None:
    """Force the file's contents out of the OS cache before we rename it."""
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _flush_directory(path: Path) -> None:
    """Force the rename itself to be durable.

    Not every platform lets you open a directory, and Windows does not, so a
    failure here is not fatal — the rename has still happened, it is just not
    yet guaranteed to survive a power cut.
    """
    try:
        handle = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)
