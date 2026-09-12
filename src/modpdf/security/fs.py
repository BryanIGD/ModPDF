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
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FileSystemError",
    "SyncedLocation",
    "atomic_write",
    "private_scratch_dir",
    "resolve_input",
    "synced_location",
]


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


def private_scratch_dir() -> Path:
    """A private directory for files this process writes for its own use.

    The desktop app needs one for building a combined workspace out of more
    than one PDF, which happens when you open a second file while one is
    already open: pdfium and every whole-document task function both
    need a real path on disk, so the combined result has to be written
    somewhere before it can become the session's document. This is not
    output the user asked to save — it is scratch state the session is built
    on, and it is cleaned up when the window closes.

    `mkstemp`'s 0600-and-O_EXCL guarantee is for files, not directories, so
    the 0700 permission is set explicitly here rather than assumed from the
    platform default.
    """
    created = Path(tempfile.mkdtemp(prefix="modpdf-workspace-"))
    created.chmod(0o700)
    return created


def _flush_to_disk(path: Path) -> None:
    """Force the file's contents out of the OS cache before we rename it.

    Opened for writing rather than reading, which looks redundant and is not:
    Windows implements fsync as _commit, which needs a writable handle and
    fails with EBADF on a read-only one. POSIX does not care either way. We
    created this file ourselves with mode 0600, so the access is ours to take.
    """
    handle = os.open(path, os.O_RDWR)
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


@dataclass(frozen=True)
class SyncedLocation:
    """A cloud-sync folder, and the service that would upload what lands in it."""

    service: str
    root: Path


# Where the major services put their folders. Names are matched against the
# directory itself, since providers append the account to it — a Google Drive
# folder is "GoogleDrive-someone@example.com", and we report "Google Drive"
# rather than repeating somebody's email address back at them.
_HOME_FOLDER_NAMES = (
    "Dropbox",
    "Google Drive",
    "OneDrive",
    "Box Sync",
    "Insync",
    "pCloud Drive",
    "Nextcloud",
    "Sync",
    "MEGA",
    "Tresorit",
)


def synced_location(path: Path) -> SyncedLocation | None:
    """Return the cloud-sync folder this path lives in, if it is in one.

    This exists because "your documents never leave your computer" is simply
    false if the output lands in a Dropbox folder. The document would be
    uploaded within seconds — not by us, but the user's confidentiality is gone
    either way, and they would have no reason to suspect it. So we look, and we
    say so.

    Detection is by location, which catches the standard case and is honest
    about what it cannot catch: a service configured to mirror an arbitrary
    folder — Google Drive can be told to sync ~/Documents itself — leaves no
    trace in the path, and this will not see it. A warning that appears is
    reliable; the absence of one is not proof of anything.
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None

    for service, root in _sync_roots():
        if resolved == root or resolved.is_relative_to(root):
            return SyncedLocation(service=service, root=root)
    return None


def _sync_roots() -> list[tuple[str, Path]]:
    """Every cloud-sync folder we can find for the current user."""
    home = Path.home()
    roots: list[tuple[str, Path]] = []

    # macOS puts iCloud Drive here, under a name no one would guess.
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if icloud.is_dir():
        roots.append(("iCloud Drive", icloud))

    # Since Big Sur, third-party providers live under one directory as File
    # Provider extensions, one subdirectory per connected account.
    cloud_storage = home / "Library" / "CloudStorage"
    if cloud_storage.is_dir():
        try:
            for entry in sorted(cloud_storage.iterdir()):
                if entry.is_dir():
                    roots.append((_service_name(entry.name), entry))
        except OSError:
            pass

    # The traditional layout, still used on Linux and Windows and by older
    # macOS installations.
    for name in _HOME_FOLDER_NAMES:
        candidate = home / name
        if candidate.is_dir():
            roots.append((name, candidate))

    # OneDrive appends the tenant: "OneDrive - Contoso".
    try:
        for candidate in sorted(home.glob("OneDrive*")):
            if candidate.is_dir() and ("OneDrive", candidate) not in roots:
                roots.append(("OneDrive", candidate))
    except OSError:
        pass

    return roots


# How each provider spells its own name. Splitting camel case automatically
# gets "GoogleDrive" right and "OneDrive" wrong, and a tool that misspells a
# product name in a security warning looks careless at the worst moment.
_SERVICE_NAMES = {
    "googledrive": "Google Drive",
    "onedrive": "OneDrive",
    "dropbox": "Dropbox",
    "box": "Box",
    "icloud": "iCloud Drive",
    "pcloud": "pCloud",
    "nextcloud": "Nextcloud",
    "owncloud": "ownCloud",
    "mega": "MEGA",
    "protondrive": "Proton Drive",
    "tresorit": "Tresorit",
    "sync.com": "Sync.com",
    "insync": "Insync",
}


def _service_name(directory_name: str) -> str:
    """Turn a provider directory name into something worth showing a person.

    "GoogleDrive-someone@example.com" becomes "Google Drive". The account is
    dropped deliberately: it is not needed to make the point, and echoing
    somebody's email address into terminal output is its own small leak.
    """
    base = directory_name.split("-", 1)[0].strip()
    known = _SERVICE_NAMES.get(base.lower())
    if known:
        return known
    # Unknown provider: fall back to splitting camel case, which is right more
    # often than it is wrong, and better than showing the raw directory name.
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base) or directory_name
