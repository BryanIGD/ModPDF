"""Tests for `inspect`.

Each detection gets its own test. A security report that misses something is
worse than no report, because the user reads "nothing notable" and believes it.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from modpdf.inspection import count_revisions, inspect_document
from tests.conftest import build_hostile_pdf, build_pdf, build_photo_pdf


@pytest.fixture
def hostile(tmp_path: Path) -> Path:
    return build_hostile_pdf(tmp_path / "hostile.pdf")


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    return build_pdf(tmp_path / "plain.pdf", 3, title="Quarterly Results")


class TestBasicFacts:
    def test_reports_page_count_and_size(self, plain: Path) -> None:
        found = inspect_document(plain)
        assert found.page_count == 3
        assert found.size_bytes == plain.stat().st_size
        assert found.pdf_version.startswith("1.")

    def test_reads_metadata(self, plain: Path) -> None:
        assert inspect_document(plain).metadata["/Title"] == "Quarterly Results"

    def test_lists_fonts(self, plain: Path) -> None:
        assert "Helvetica" in inspect_document(plain).fonts

    def test_counts_images(self, tmp_path: Path) -> None:
        """Images are streams, and the scan used to look only at plain
        dictionaries, so every document was reported as having none."""
        assert inspect_document(build_photo_pdf(tmp_path / "photo.pdf")).image_count == 1

    def test_a_soft_mask_is_not_counted_as_a_second_image(self, tmp_path: Path) -> None:
        path = tmp_path / "masked.pdf"
        with pikepdf.new() as pdf:
            pdf.add_blank_page()
            mask = pikepdf.Stream(pdf, b"\xff" * 4)
            mask.Type, mask.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
            mask.Width, mask.Height, mask.BitsPerComponent = 2, 2, 8
            mask.ColorSpace = pikepdf.Name.DeviceGray
            image = pikepdf.Stream(pdf, b"\x80" * 12)
            image.Type, image.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
            image.Width, image.Height, image.BitsPerComponent = 2, 2, 8
            image.ColorSpace, image.SMask = pikepdf.Name.DeviceRGB, mask
            pdf.pages[0].obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
            pdf.save(path)
        assert inspect_document(path).image_count == 1

    def test_a_document_without_images_reports_none(self, plain: Path) -> None:
        assert inspect_document(plain).image_count == 0

    def test_unencrypted_document_reports_no_permissions(self, plain: Path) -> None:
        found = inspect_document(plain)
        assert found.encrypted is False
        assert found.permissions == {}


class TestDetections:
    def test_finds_javascript(self, hostile: Path) -> None:
        assert inspect_document(hostile).javascript >= 1

    def test_finds_the_open_action(self, hostile: Path) -> None:
        assert inspect_document(hostile).has_open_action is True

    def test_finds_a_launch_action(self, hostile: Path) -> None:
        assert inspect_document(hostile).actions.get("/Launch") == 1

    def test_finds_a_tracking_uri(self, hostile: Path) -> None:
        found = inspect_document(hostile)
        assert found.actions.get("/URI") == 1
        assert "http://tracker.example.com/beacon" in found.uris

    def test_finds_embedded_files_by_name(self, hostile: Path) -> None:
        assert inspect_document(hostile).embedded_files == ("payroll.xlsx",)

    def test_finds_an_xfa_form(self, hostile: Path) -> None:
        assert inspect_document(hostile).xfa is True

    def test_a_plain_document_trips_nothing(self, plain: Path) -> None:
        found = inspect_document(plain)
        assert found.javascript == 0
        assert found.has_open_action is False
        assert found.actions == {}
        assert found.embedded_files == ()
        assert found.xfa is False
        assert found.uris == ()


class TestConcerns:
    """The user-facing layer: every finding must come with an explanation."""

    def test_hostile_document_raises_several_concerns(self, hostile: Path) -> None:
        labels = {c.label for c in inspect_document(hostile).concerns}
        assert "JavaScript" in labels
        assert "Opens automatically" in labels
        assert "Embedded files" in labels
        assert "XFA form" in labels

    def test_every_concern_explains_itself(self, hostile: Path) -> None:
        for concern in inspect_document(hostile).concerns:
            assert concern.detail, f"{concern.label} says nothing about what was found"
            assert len(concern.why) > 30, f"{concern.label} does not explain why it matters"

    def test_javascript_is_reported_first(self, hostile: Path) -> None:
        """It is the most likely to actually hurt someone, so it leads."""
        assert inspect_document(hostile).concerns[0].label == "JavaScript"

    def test_javascript_is_not_double_counted_as_a_generic_action(self, hostile: Path) -> None:
        labels = [c.label for c in inspect_document(hostile).concerns]
        assert "JavaScript action" not in labels

    def test_a_plain_document_only_flags_its_metadata(self, plain: Path) -> None:
        labels = [c.label for c in inspect_document(plain).concerns]
        assert labels == ["Identifying metadata"]


class TestRevisionCounting:
    """Pure byte counting, tested directly rather than through a crafted file."""

    def test_a_single_save_is_one_revision(self) -> None:
        assert count_revisions(b"%PDF-1.7 ... %%EOF\n") == 1

    def test_each_appended_save_adds_one(self) -> None:
        assert count_revisions(b"a %%EOF b %%EOF c %%EOF") == 3

    def test_never_reports_fewer_than_one(self) -> None:
        """A file with no marker at all is damaged, not zero-revision."""
        assert count_revisions(b"not really a pdf") == 1

    def test_a_normal_document_reports_one_revision(self, plain: Path) -> None:
        assert inspect_document(plain).revisions == 1

    def test_linearization_is_not_mistaken_for_an_edit(self, tmp_path: Path) -> None:
        """A linearized file writes two markers in one save; that is not two saves."""
        import pikepdf

        source = build_pdf(tmp_path / "source.pdf", 4)
        linear = tmp_path / "linear.pdf"
        with pikepdf.open(source) as pdf:
            pdf.save(linear, linearize=True)

        found = inspect_document(linear)
        assert found.linearized is True
        assert found.revisions == 1, "linearization must not look like a hidden revision"


class TestItChangesNothing:
    def test_inspecting_does_not_modify_the_file(self, hostile: Path) -> None:
        before = hostile.read_bytes()
        inspect_document(hostile)
        assert hostile.read_bytes() == before
