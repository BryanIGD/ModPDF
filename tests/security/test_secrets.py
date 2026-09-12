"""Tests for password handling.

The important property is negative and cannot be asserted directly: no password
ever reaches the command line. What we can assert is that the only way in is
stdin, the environment, or a prompt — and that no --password option exists to
put one in `ps` output in the first place.
"""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest
from typer.testing import CliRunner

from modpdf.cli import app
from modpdf.document import EncryptedDocumentError, open_pdf
from modpdf.security import secrets
from tests.conftest import PageMaker, page_markers, plain_cli_output

runner = CliRunner()
PASSWORD = "hunter2"


@pytest.fixture
def locked(make_pdf: PageMaker, tmp_path: Path) -> Path:
    """A real encrypted PDF, AES-256 (revision 6)."""
    plain = make_pdf(6, name="plain.pdf")
    out = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(
            out,
            encryption=pikepdf.Encryption(owner="owner-pw", user=PASSWORD, R=6),
        )
    return out


class TestThereIsNoPasswordFlag:
    def test_no_command_accepts_a_password_as_an_argument(self) -> None:
        """A --password VALUE flag would expose the password through `ps`."""
        for command in ("split", "merge", "reorder", "inspect"):
            help_text = plain_cli_output(runner.invoke(app, [command, "--help"]).output)
            assert "--password-stdin" in help_text or command == "merge"
            assert "--password TEXT" not in help_text
            assert "--password " not in help_text.replace("--password-stdin", "")


class TestResolve:
    def test_reads_one_line_from_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))
        assert secrets.resolve(use_stdin=True) == "s3cret"

    def test_keeps_leading_and_trailing_spaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trimming them would produce a wrong password the user cannot explain."""
        monkeypatch.setattr("sys.stdin", io.StringIO("  pad ded  \n"))
        assert secrets.resolve(use_stdin=True) == "  pad ded  "

    def test_strips_only_the_line_ending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("windows\r\n"))
        assert secrets.resolve(use_stdin=True) == "windows"

    def test_empty_stdin_is_no_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert secrets.resolve(use_stdin=True) is None

    def test_falls_back_to_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, "from-env")
        assert secrets.resolve() == "from-env"

    def test_stdin_wins_over_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, "from-env")
        monkeypatch.setattr("sys.stdin", io.StringIO("from-stdin\n"))
        assert secrets.resolve(use_stdin=True) == "from-stdin"

    def test_nothing_supplied_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(secrets.ENVIRONMENT_VARIABLE, raising=False)
        assert secrets.resolve() is None


class TestOpeningEncryptedDocuments:
    def test_the_right_password_opens_it(self, locked: Path) -> None:
        with open_pdf(locked, password=PASSWORD) as pdf:
            assert len(pdf.pages) == 6

    def test_no_password_is_a_clear_error(self, locked: Path) -> None:
        with pytest.raises(EncryptedDocumentError, match="needs a password"):
            with open_pdf(locked):
                pass

    def test_a_wrong_password_says_so(self, locked: Path) -> None:
        with pytest.raises(EncryptedDocumentError, match="password is wrong"):
            with open_pdf(locked, password="not-it"):
                pass

    def test_a_wrong_password_does_not_suggest_supplying_one(self, locked: Path) -> None:
        """Telling someone to pass --password-stdin when they just did is noise."""
        with pytest.raises(EncryptedDocumentError) as raised:
            with open_pdf(locked, password="not-it"):
                pass
        assert "--password-stdin" not in str(raised.value)

    def test_the_password_is_never_in_the_error_message(self, locked: Path) -> None:
        with pytest.raises(EncryptedDocumentError) as raised:
            with open_pdf(locked, password="p@ssw0rd-leak-canary"):
                pass
        assert "leak-canary" not in str(raised.value)


class TestCommandsOnEncryptedDocuments:
    def test_split(self, locked: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, PASSWORD)
        result = runner.invoke(
            app, ["split", str(locked), "--every", "3", "-o", str(tmp_path / "out")]
        )
        assert result.exit_code == 0
        pieces = sorted((tmp_path / "out").iterdir())
        assert [page_markers(p) for p in pieces] == [[1, 2, 3], [4, 5, 6]]

    def test_merge(self, locked: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """merge could not open encrypted documents at all before Phase 2."""
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, PASSWORD)
        out = tmp_path / "merged.pdf"
        result = runner.invoke(app, ["merge", str(locked), str(locked), "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [1, 2, 3, 4, 5, 6] * 2

    def test_reorder(self, locked: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, PASSWORD)
        out = tmp_path / "out.pdf"
        result = runner.invoke(app, ["reorder", str(locked), "--order", "-1,1", "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [6, 1]

    def test_inspect_reports_encryption_and_permissions(
        self, locked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(secrets.ENVIRONMENT_VARIABLE, PASSWORD)
        result = runner.invoke(app, ["inspect", str(locked)])
        assert result.exit_code == 0
        output = plain_cli_output(result.output)
        assert "encrypted" in output
        assert "Permissions" in output

    def test_without_a_password_it_fails_cleanly(
        self, locked: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(secrets.ENVIRONMENT_VARIABLE, raising=False)
        result = runner.invoke(
            app, ["reorder", str(locked), "--order", "1", "-o", str(tmp_path / "o.pdf")]
        )
        assert result.exit_code == 1
        assert "needs a password" in plain_cli_output(result.output)
        assert not (tmp_path / "o.pdf").exists()
