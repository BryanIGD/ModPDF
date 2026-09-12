"""Tests for atomic, private-by-default file writing.

The guarantees here are the ones a user of a privacy tool is implicitly relying
on, so they are tested directly rather than through the commands that use them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from modpdf.security.fs import FileSystemError, atomic_write, resolve_input


class TestAtomicWrite:
    def test_writes_the_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        with atomic_write(target) as staged:
            staged.write_bytes(b"contents")
        assert target.read_bytes() == b"contents"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_output_is_not_readable_by_others(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        with atomic_write(target) as staged:
            staged.write_bytes(b"secret")
        assert target.stat().st_mode & 0o077 == 0

    def test_a_failure_leaves_no_output_at_all(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        with pytest.raises(RuntimeError):
            with atomic_write(target) as staged:
                staged.write_bytes(b"half a document")
                raise RuntimeError("something went wrong mid-write")

        assert not target.exists(), "a partial file is worse than no file"
        assert list(tmp_path.iterdir()) == [], "the staged file was not cleaned up"

    def test_a_failure_leaves_an_existing_file_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        target.write_bytes(b"the original")

        with pytest.raises(RuntimeError):
            with atomic_write(target, overwrite=True) as staged:
                staged.write_bytes(b"the replacement")
                raise RuntimeError("boom")

        assert target.read_bytes() == b"the original"

    def test_refuses_to_overwrite_by_default(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        target.write_bytes(b"existing")
        with pytest.raises(FileSystemError, match="already exists"):
            with atomic_write(target) as staged:
                staged.write_bytes(b"new")
        assert target.read_bytes() == b"existing"

    def test_overwrites_when_asked(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        target.write_bytes(b"existing")
        with atomic_write(target, overwrite=True) as staged:
            staged.write_bytes(b"new")
        assert target.read_bytes() == b"new"

    def test_missing_directory_is_reported_clearly(self, tmp_path: Path) -> None:
        with pytest.raises(FileSystemError, match="does not exist"):
            with atomic_write(tmp_path / "nope" / "out.bin"):
                pass

    def test_writing_nothing_is_an_error_not_an_empty_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        with pytest.raises(FileSystemError, match="nothing was written"):
            with atomic_write(target) as staged:
                staged.unlink()
        assert not target.exists()

    def test_staging_happens_in_the_destination_directory(self, tmp_path: Path) -> None:
        """So the final rename is atomic, which it is not across filesystems."""
        target = tmp_path / "out.bin"
        with atomic_write(target) as staged:
            assert staged.parent == tmp_path
            staged.write_bytes(b"x")


class TestResolveInput:
    def test_returns_a_resolved_path(self, tmp_path: Path) -> None:
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF-")
        assert resolve_input(source) == source.resolve()

    def test_follows_a_symlink_to_the_real_file(self, tmp_path: Path) -> None:
        real = tmp_path / "real.pdf"
        real.write_bytes(b"%PDF-")
        link = tmp_path / "link.pdf"
        link.symlink_to(real)
        assert resolve_input(link) == real.resolve()

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileSystemError, match="no such file"):
            resolve_input(tmp_path / "ghost.pdf")

    def test_directory(self, tmp_path: Path) -> None:
        with pytest.raises(FileSystemError, match="is a directory"):
            resolve_input(tmp_path)

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fifo")
    def test_refuses_a_fifo(self, tmp_path: Path) -> None:
        """Opening a device node or pipe and calling it a PDF ends badly."""
        # The marker skips this at run time on Windows; the inner check is what
        # tells mypy, which type checks the suite for Windows too, that
        # os.mkfifo is not being reached on a platform that lacks it.
        if sys.platform != "win32":
            fifo = tmp_path / "pipe.pdf"
            os.mkfifo(fifo)
            with pytest.raises(FileSystemError, match="not a regular file"):
                resolve_input(fifo)

    def test_broken_symlink(self, tmp_path: Path) -> None:
        link = tmp_path / "link.pdf"
        link.symlink_to(tmp_path / "gone.pdf")
        with pytest.raises(FileSystemError, match="no such file"):
            resolve_input(link)
