"""Tests for cloud-sync folder detection.

The claim "your documents never leave your computer" is false the moment output
lands in a Dropbox folder, and the user has no reason to be thinking about that
while typing an output path. These tests use a fake home directory so they
behave the same on a developer's machine as in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from modpdf.cli import app
from modpdf.security.fs import synced_location
from tests.conftest import PageMaker, plain_cli_output

runner = CliRunner()


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory containing the sync folders the real services create."""
    home = tmp_path / "home"
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)
    (home / "Library" / "CloudStorage" / "Dropbox").mkdir(parents=True)
    (home / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com").mkdir()
    (home / "Library" / "CloudStorage" / "OneDrive-Contoso").mkdir()
    (home / "Dropbox").mkdir()
    (home / "Documents").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


class TestDetection:
    def test_icloud_drive(self, fake_home: Path) -> None:
        target = fake_home / "Library/Mobile Documents/com~apple~CloudDocs/tax.pdf"
        found = synced_location(target)
        assert found is not None
        assert found.service == "iCloud Drive"

    def test_dropbox_under_cloudstorage(self, fake_home: Path) -> None:
        found = synced_location(fake_home / "Library/CloudStorage/Dropbox/nda.pdf")
        assert found is not None
        assert found.service == "Dropbox"

    def test_dropbox_in_the_traditional_location(self, fake_home: Path) -> None:
        found = synced_location(fake_home / "Dropbox/nda.pdf")
        assert found is not None
        assert found.service == "Dropbox"

    def test_google_drive_name_is_split_into_words(self, fake_home: Path) -> None:
        base = fake_home / "Library/CloudStorage/GoogleDrive-someone@example.com"
        found = synced_location(base / "payroll.pdf")
        assert found is not None
        assert found.service == "Google Drive"

    def test_the_account_is_not_echoed_back(self, fake_home: Path) -> None:
        """Printing somebody's email address into terminal output is its own leak."""
        base = fake_home / "Library/CloudStorage/GoogleDrive-someone@example.com"
        found = synced_location(base / "payroll.pdf")
        assert found is not None
        assert "someone@example.com" not in found.service

    def test_onedrive_tenant_is_dropped(self, fake_home: Path) -> None:
        base = fake_home / "Library/CloudStorage/OneDrive-Contoso"
        found = synced_location(base / "budget.pdf")
        assert found is not None
        assert found.service == "OneDrive", "each provider spelled the way it spells itself"

    def test_an_unknown_provider_still_gets_a_readable_name(self, fake_home: Path) -> None:
        (fake_home / "Library" / "CloudStorage" / "AcmeVault-team").mkdir()
        found = synced_location(fake_home / "Library/CloudStorage/AcmeVault-team/x.pdf")
        assert found is not None
        assert found.service == "Acme Vault"

    def test_nested_deeply_is_still_detected(self, fake_home: Path) -> None:
        deep = fake_home / "Dropbox" / "work" / "clients" / "2026" / "contract.pdf"
        assert synced_location(deep) is not None

    def test_the_sync_root_itself_counts(self, fake_home: Path) -> None:
        assert synced_location(fake_home / "Dropbox") is not None

    def test_an_ordinary_folder_is_not_flagged(self, fake_home: Path) -> None:
        assert synced_location(fake_home / "Documents" / "contract.pdf") is None

    def test_a_lookalike_name_is_not_flagged(self, fake_home: Path) -> None:
        """A false warning teaches people to ignore warnings, so be exact.

        "Dropbox Archive" is a folder someone named themselves.
        """
        (fake_home / "Dropbox Archive").mkdir()
        assert synced_location(fake_home / "Dropbox Archive" / "old.pdf") is None

    def test_a_nonexistent_path_does_not_raise(self, fake_home: Path) -> None:
        assert synced_location(fake_home / "nowhere" / "ghost.pdf") is None


class TestTheWarningReachesTheUser:
    def test_reorder_warns_when_writing_into_a_sync_folder(
        self, fake_home: Path, make_pdf: PageMaker
    ) -> None:
        source = make_pdf(3)
        out = fake_home / "Dropbox" / "out.pdf"
        result = runner.invoke(app, ["reorder", str(source), "--order", "1", "-o", str(out)])
        assert result.exit_code == 0
        assert "Dropbox will upload it" in plain_cli_output(result.output)
        assert out.exists(), "the file is still written; we warn, we do not refuse"

    def test_split_warns_about_the_output_directory(
        self, fake_home: Path, make_pdf: PageMaker
    ) -> None:
        source = make_pdf(4)
        out_dir = fake_home / "Dropbox" / "pieces"
        result = runner.invoke(app, ["split", str(source), "--every", "2", "-o", str(out_dir)])
        assert result.exit_code == 0
        assert "Dropbox will upload it" in plain_cli_output(result.output)

    def test_merge_warns(self, fake_home: Path, make_pdf: PageMaker) -> None:
        first, second = make_pdf(2, name="a.pdf"), make_pdf(2, name="b.pdf")
        out = fake_home / "Dropbox" / "merged.pdf"
        result = runner.invoke(app, ["merge", str(first), str(second), "-o", str(out)])
        assert result.exit_code == 0
        assert "Dropbox will upload it" in plain_cli_output(result.output)

    def test_no_warning_for_an_ordinary_destination(
        self, fake_home: Path, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        source = make_pdf(3)
        result = runner.invoke(
            app, ["reorder", str(source), "--order", "1", "-o", str(tmp_path / "out.pdf")]
        )
        assert result.exit_code == 0
        assert "will upload" not in plain_cli_output(result.output)
