"""Tests for behaviour on input we did not write and should not trust.

Every PDF ModPDF opens might have been emailed to the user by a stranger. The
standard for these tests is not "it works" but "it fails safely": a clear
message, a non-zero exit, and — the part that matters most — no half-written
output file left behind for someone to mistake for a real document.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pikepdf
import pytest
from typer.testing import CliRunner

from modpdf.cli import app
from modpdf.document import DamagedDocumentError, open_pdf
from modpdf.security.limits import (
    DEFAULT_LIMITS,
    LimitExceededError,
    Limits,
    check_file_size,
    check_page_count,
)
from tests.conftest import PageMaker, build_hostile_pdf, build_pdf, page_markers

runner = CliRunner()


def corrupt(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class TestMalformedFiles:
    @pytest.mark.parametrize(
        ("name", "data"),
        [
            ("empty.pdf", b""),
            ("text.pdf", b"this is a text file someone renamed"),
            ("header-only.pdf", b"%PDF-1.7\n"),
            ("garbage-body.pdf", b"%PDF-1.7\n" + bytes(range(256)) * 40),
            ("null-bytes.pdf", b"\x00" * 2048),
            ("html.pdf", b"<!doctype html><html><body>not a pdf</body></html>"),
        ],
    )
    def test_refused_with_a_clear_message(self, tmp_path: Path, name: str, data: bytes) -> None:
        source = corrupt(tmp_path, name, data)
        with pytest.raises(DamagedDocumentError, match="cannot read"):
            with open_pdf(source):
                pass

    def test_a_truncated_document_is_repaired_but_reported(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        """QPDF rebuilds a truncated file rather than refusing it.

        That is the right behaviour — a damaged document is usually still worth
        recovering — but it must not happen silently, because the recovered
        file can be missing content the user will never think to look for.
        """
        whole = make_pdf(10).read_bytes()
        source = corrupt(tmp_path, "truncated.pdf", whole[: len(whole) // 2])

        repairs: list[str] = []
        with open_pdf(source, on_damage=repairs.extend) as pdf:
            assert len(pdf.pages) > 0
        assert repairs, "a damaged file was read without telling anybody"

    def test_repair_warnings_do_not_leak_the_full_path(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        whole = make_pdf(10).read_bytes()
        source = corrupt(tmp_path, "truncated.pdf", whole[: len(whole) // 2])

        repairs: list[str] = []
        with open_pdf(source, on_damage=repairs.extend):
            pass
        assert repairs
        assert not any(str(tmp_path) in message for message in repairs)

    def test_the_user_is_warned_on_the_command_line(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        whole = make_pdf(10).read_bytes()
        source = corrupt(tmp_path, "truncated.pdf", whole[: len(whole) // 2])
        result = runner.invoke(
            app, ["reorder", str(source), "--order", "1", "-o", str(tmp_path / "o.pdf")]
        )
        assert "is damaged" in result.output
        assert "may be missing or altered" in result.output

    def test_inspect_reports_damage_as_a_concern(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        from modpdf.inspection import inspect_document

        whole = make_pdf(10).read_bytes()
        source = corrupt(tmp_path, "truncated.pdf", whole[: len(whole) // 2])

        found = inspect_document(source)
        assert found.repairs
        assert found.concerns[0].label == "Damaged file"

    def test_the_error_names_the_file_not_the_internals(self, tmp_path: Path) -> None:
        source = corrupt(tmp_path, "junk.pdf", b"nope")
        with pytest.raises(DamagedDocumentError) as raised:
            with open_pdf(source):
                pass
        assert "junk.pdf" in str(raised.value)


class TestFailureLeavesNothingBehind:
    @pytest.mark.parametrize("command", ["reorder", "split"])
    def test_no_output_after_a_malformed_input(self, tmp_path: Path, command: str) -> None:
        source = corrupt(tmp_path, "junk.pdf", b"not a pdf")
        target = tmp_path / "out"
        args = (
            ["reorder", str(source), "--order", "1", "-o", str(target / "x.pdf")]
            if command == "reorder"
            else ["split", str(source), "--every", "2", "-o", str(target)]
        )
        target.mkdir()

        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert list(target.iterdir()) == [], "a failed run must leave no files"

    def test_no_stray_temporary_files(self, tmp_path: Path) -> None:
        """The staged .part file must be cleaned up even on an unexpected failure."""
        source = corrupt(tmp_path, "junk.pdf", b"not a pdf")
        out = tmp_path / "out.pdf"
        runner.invoke(app, ["reorder", str(source), "--order", "1", "-o", str(out)])
        leftovers = [p.name for p in tmp_path.iterdir() if p.name != "junk.pdf"]
        assert leftovers == []

    def test_an_existing_file_survives_a_failed_run(
        self, tmp_path: Path, make_pdf: PageMaker
    ) -> None:
        source = make_pdf(3)
        out = tmp_path / "out.pdf"
        out.write_bytes(b"something the user cares about")

        result = runner.invoke(
            app, ["reorder", str(source), "--order", "99", "-o", str(out), "--force"]
        )
        assert result.exit_code == 1
        assert out.read_bytes() == b"something the user cares about"


class TestResourceLimits:
    def test_an_oversized_file_is_refused_before_it_is_parsed(self, tmp_path: Path) -> None:
        source = corrupt(tmp_path, "big.pdf", b"x" * 5000)
        with pytest.raises(LimitExceededError, match="above the"):
            check_file_size(source, Limits(max_file_bytes=1000))

    def test_a_normal_file_passes(self, make_pdf: PageMaker) -> None:
        check_file_size(make_pdf(3), DEFAULT_LIMITS)

    def test_too_many_pages_is_refused(self) -> None:
        with pytest.raises(LimitExceededError, match="page limit"):
            check_page_count(200_000, Limits(max_pages=1000))

    def test_the_size_limit_applies_when_opening(self, make_pdf: PageMaker) -> None:
        source = make_pdf(5)
        with pytest.raises(LimitExceededError):
            with open_pdf(source, limits=Limits(max_file_bytes=100)):
                pass

    def test_the_page_limit_applies_when_opening(self, make_pdf: PageMaker) -> None:
        source = make_pdf(10)
        with pytest.raises(LimitExceededError):
            with open_pdf(source, limits=Limits(max_pages=3)):
                pass

    def test_the_limit_error_suggests_what_to_do(self, tmp_path: Path) -> None:
        """Someone with a genuinely huge document should not be left stuck."""
        source = corrupt(tmp_path, "big.pdf", b"x" * 5000)
        with pytest.raises(LimitExceededError) as raised:
            check_file_size(source, Limits(max_file_bytes=1000))
        assert "open an issue" in str(raised.value)


class TestActiveContentIsNeverExecuted:
    """We read these documents. We do not run anything they contain."""

    def test_a_document_with_javascript_can_still_be_processed(self, tmp_path: Path) -> None:
        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        out = tmp_path / "out.pdf"
        result = runner.invoke(app, ["reorder", str(source), "--order", "2,1", "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [2, 1]

    def test_an_open_action_does_not_travel_into_selected_pages(self, tmp_path: Path) -> None:
        """Rebuilding the document drops catalog-level actions as a side effect."""
        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        out = tmp_path / "out.pdf"
        runner.invoke(app, ["reorder", str(source), "--order", "1-3", "-o", str(out)])

        with pikepdf.open(out) as pdf:
            assert "/OpenAction" not in pdf.Root
            assert "/Names" not in pdf.Root


class TestOddFilesystemInputs:
    def test_a_directory_is_refused(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["reorder", str(tmp_path), "--order", "1", "-o", str(tmp_path / "o.pdf")]
        )
        assert result.exit_code == 1
        assert "is a directory" in result.output

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fifo")
    def test_a_fifo_is_refused_rather_than_read(self, tmp_path: Path) -> None:
        """Opening a pipe and waiting forever is a denial of service on ourselves."""
        # The marker skips this at run time on Windows; the inner check is what
        # tells mypy, which type checks the suite for Windows too, that
        # os.mkfifo is not being reached on a platform that lacks it.
        if sys.platform != "win32":
            import os

            fifo = tmp_path / "pipe.pdf"
            os.mkfifo(fifo)
            result = runner.invoke(
                app, ["reorder", str(fifo), "--order", "1", "-o", str(tmp_path / "o.pdf")]
            )
            assert result.exit_code == 1
            assert "not a regular file" in result.output


class TestDeeplyNestedStructures:
    def test_a_deep_outline_does_not_blow_the_stack(self, tmp_path: Path) -> None:
        """pikepdf bounds outline depth at 16; this asserts we rely on that safely."""
        base = build_pdf(tmp_path / "base.pdf", 2)
        source = tmp_path / "deep.pdf"

        pdf = pikepdf.open(base)
        with pdf.open_outline() as outline:
            root = pikepdf.OutlineItem("level 0", 0)
            node = root
            for depth in range(1, 5000):
                child = pikepdf.OutlineItem(f"level {depth}", 0)
                node.children.append(child)
                node = child
            outline.root.append(root)
        pdf.save(source)
        pdf.close()

        out = tmp_path / "out.pdf"
        result = runner.invoke(app, ["reorder", str(source), "--order", "2,1", "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [2, 1]
