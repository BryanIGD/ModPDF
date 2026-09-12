"""End-to-end tests through the actual command line.

These assert on page identity, not page counts. A command that returns the
right number of wrong pages is the failure mode worth catching.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from modpdf.cli import app
from tests.conftest import PageMaker, page_markers

runner = CliRunner()


def run(*args: str | Path) -> Result:
    return runner.invoke(app, [str(a) for a in args])


class TestSplit:
    def test_every_n_pages(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(23, name="contract.pdf")
        result = run("split", source, "--every", "10", "-o", tmp_path / "out")
        assert result.exit_code == 0

        pieces = sorted((tmp_path / "out").iterdir())
        assert [p.name for p in pieces] == [
            "contract-p001-010.pdf",
            "contract-p011-020.pdf",
            "contract-p021-023.pdf",
        ]
        assert page_markers(pieces[0]) == list(range(1, 11))
        assert page_markers(pieces[2]) == [21, 22, 23]

    def test_each_page_group_becomes_a_file(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(15, name="report.pdf")
        result = run("split", source, "--pages", "1-3,7,12-", "-o", tmp_path / "out")
        assert result.exit_code == 0

        pieces = sorted((tmp_path / "out").iterdir())
        assert [page_markers(p) for p in pieces] == [[1, 2, 3], [7], [12, 13, 14, 15]]

    def test_dry_run_writes_nothing(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(10)
        result = run("split", source, "--every", "5", "-o", tmp_path / "out", "--dry-run")
        assert result.exit_code == 0
        assert not (tmp_path / "out").exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_split_directory_is_private(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        """Pieces of a confidential document should not be world-readable."""
        source = make_pdf(4)
        run("split", source, "--every", "2", "-o", tmp_path / "out")
        assert (tmp_path / "out").stat().st_mode & 0o077 == 0
        for piece in (tmp_path / "out").iterdir():
            assert piece.stat().st_mode & 0o077 == 0

    def test_needs_exactly_one_mode(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(10)
        both = run("split", source, "--every", "5", "--pages", "1-2", "-o", tmp_path / "o")
        neither = run("split", source, "-o", tmp_path / "o")
        assert both.exit_code == 1
        assert neither.exit_code == 1
        assert "exactly one" in both.output


class TestMerge:
    def test_joins_in_argument_order(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        first = make_pdf(3, name="a.pdf")
        second = make_pdf(2, name="b.pdf")
        out = tmp_path / "merged.pdf"

        assert run("merge", first, second, "-o", out).exit_code == 0
        assert page_markers(out) == [1, 2, 3, 1, 2]

    def test_refuses_a_single_file(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        result = run("merge", make_pdf(3), "-o", tmp_path / "merged.pdf")
        assert result.exit_code == 1
        assert "at least two" in result.output


class TestReorder:
    def test_rearranges(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(5)
        out = tmp_path / "out.pdf"
        assert run("reorder", source, "--order", "3,1,2,5-5", "-o", out).exit_code == 0
        assert page_markers(out) == [3, 1, 2, 5]

    def test_last_page_shorthand(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(9)
        out = tmp_path / "out.pdf"
        assert run("reorder", source, "--order", "-1,1", "-o", out).exit_code == 0
        assert page_markers(out) == [9, 1]

    def test_duplicating_a_page_is_allowed(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(3)
        out = tmp_path / "out.pdf"
        assert run("reorder", source, "--order", "1,1,1", "-o", out).exit_code == 0
        assert page_markers(out) == [1, 1, 1]

    def test_warns_when_pages_are_dropped(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        result = run("reorder", make_pdf(10), "--order", "1-3", "-o", tmp_path / "o.pdf")
        assert result.exit_code == 0
        assert "dropped" in result.output


class TestFailureIsSafe:
    def test_will_not_overwrite_without_force(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(3)
        out = tmp_path / "out.pdf"
        out.write_bytes(b"not a pdf, but precious")

        result = run("reorder", source, "--order", "1", "-o", out)
        assert result.exit_code == 1
        assert "already exists" in result.output
        assert out.read_bytes() == b"not a pdf, but precious"

    def test_force_overwrites(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(3)
        out = tmp_path / "out.pdf"
        out.write_bytes(b"old")
        assert run("reorder", source, "--order", "1", "-o", out, "--force").exit_code == 0
        assert page_markers(out) == [1]

    def test_missing_input_is_a_clean_error(self, tmp_path: Path) -> None:
        result = run("reorder", tmp_path / "ghost.pdf", "--order", "1", "-o", tmp_path / "o.pdf")
        assert result.exit_code == 1
        assert "no such file" in result.output

    def test_not_a_pdf_is_a_clean_error(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.pdf"
        junk.write_bytes(b"this is not a PDF at all")
        result = run("reorder", junk, "--order", "1", "-o", tmp_path / "o.pdf")
        assert result.exit_code == 1
        assert "cannot read" in result.output

    def test_page_out_of_range_leaves_no_output(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        out = tmp_path / "o.pdf"
        result = run("reorder", make_pdf(3), "--order", "99", "-o", out)
        assert result.exit_code == 1
        assert not out.exists()


def test_version() -> None:
    result = run("--version")
    assert result.exit_code == 0
    assert "modpdf" in result.output


class TestInspect:
    def test_reports_a_clean_document(self, make_pdf: PageMaker) -> None:
        result = run("inspect", make_pdf(3))
        assert result.exit_code == 0
        assert "3 pages" in result.output

    def test_flags_a_hostile_document(self, tmp_path: Path) -> None:
        from tests.conftest import build_hostile_pdf

        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        result = run("inspect", source)
        assert result.exit_code == 0
        assert "JavaScript" in result.output
        assert "Embedded files" in result.output

    def test_json_output_is_parseable(self, tmp_path: Path) -> None:
        import json

        from tests.conftest import build_hostile_pdf

        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        result = run("inspect", source, "--json")
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["page_count"] == 3
        assert payload["javascript"] >= 1

    def test_it_does_not_modify_the_document(self, make_pdf: PageMaker) -> None:
        source = make_pdf(4)
        before = source.read_bytes()
        assert run("inspect", source).exit_code == 0
        assert source.read_bytes() == before


class TestSanitize:
    def test_cleans_and_reports(self, tmp_path: Path) -> None:
        from tests.conftest import build_hostile_pdf

        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        out = tmp_path / "clean.pdf"
        result = run("sanitize", source, "-o", out)

        assert result.exit_code == 0
        assert "removed:" in result.output
        assert "JavaScript" in result.output
        assert page_markers(out) == [1, 2, 3]
        assert b"app.alert" not in out.read_bytes()

    def test_says_so_when_there_is_nothing_to_do(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(2)
        once = tmp_path / "once.pdf"
        run("sanitize", source, "-o", once)
        result = run("sanitize", once, "-o", tmp_path / "twice.pdf")
        assert result.exit_code == 0
        assert "already clean" in result.output

    def test_warns_that_it_is_not_redaction(self, tmp_path: Path) -> None:
        from tests.conftest import build_hostile_pdf

        source = build_hostile_pdf(tmp_path / "hostile.pdf")
        result = run("sanitize", source, "-o", tmp_path / "clean.pdf")
        assert "not redaction" in result.output

    def test_will_not_overwrite_without_force(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(2)
        out = tmp_path / "clean.pdf"
        out.write_bytes(b"precious")
        result = run("sanitize", source, "-o", out)
        assert result.exit_code == 1
        assert out.read_bytes() == b"precious"
