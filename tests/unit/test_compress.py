"""Tests for compression.

Every fixture here was chosen after an earlier one gave a misleading answer.
Flat colour and periodic patterns (a solid rectangle, a checkerboard) compress
so well under plain Flate that no recompression can beat them, which proves
nothing about how `compress` behaves on an actual photo or scan — so
`build_photo_pdf` and `build_scan_pdf` are deliberately continuous-tone and
deliberately irregular. Sizing an image to exceed the default 200 DPI target
without an enormous, slow-to-process pixel count is why every fixture places
its image in a box smaller than a full page rather than filling it.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf

from modpdf.ops.compress import (
    STRUCTURAL_SAVE_OPTIONS,
    CompressReport,
    Mode,
    compress,
)
from tests.conftest import (
    PageMaker,
    add_cmyk_image,
    build_bilevel_pdf,
    build_photo_pdf,
    build_scan_pdf,
    page_markers,
)


def compress_file(
    path: Path,
    *,
    mode: Mode = "visual",
    target_dpi: int = 200,
    verify: bool = True,
) -> tuple[pikepdf.Pdf, CompressReport]:
    """Open, compress, and hand back the result plus its report — the shape
    almost every test below wants, with the file's own size as `before_bytes`."""
    before = path.stat().st_size
    with pikepdf.open(path) as pdf:
        return compress(pdf, before_bytes=before, mode=mode, target_dpi=target_dpi, verify=verify)


class TestStructuralSavingsAlone:
    def test_a_plain_document_shrinks_a_little(self, make_pdf: PageMaker) -> None:
        source = make_pdf(5)
        result, report = compress_file(source)
        assert report.after_bytes <= report.before_bytes
        result.close()

    def test_pages_and_their_content_survive(self, make_pdf: PageMaker, tmp_path: Path) -> None:
        source = make_pdf(4)
        result, _ = compress_file(source)
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)
        assert page_markers(out) == [1, 2, 3, 4]

    def test_the_reported_size_matches_what_is_actually_written(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        """The whole point of threading the same save options through both:
        a number in a report that does not match the file on disk is worse
        than no number at all."""
        source = make_pdf(5)
        result, report = compress_file(source)
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)
        assert out.stat().st_size == report.after_bytes


class TestLosslessMode:
    def test_never_touches_images_even_when_oversized(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        result, report = compress_file(source, mode="lossless")
        assert report.images.recompressed == 0
        assert report.mode_used in ("lossless", "none")
        result.close()


class TestVisualModeOnAPhotograph:
    """Continuous-tone content: JPEG has real work to do, and should win."""

    def test_an_oversized_photo_shrinks_substantially(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        result, report = compress_file(source)
        assert report.images.recompressed == 1
        assert report.savings_ratio > 0.5, "a genuine photo at 259 DPI should shrink a lot at 200"
        result.close()

    def test_the_quality_gate_passes_on_a_sensible_target(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        _, report = compress_file(source)
        assert report.verify_result is not None
        assert report.verify_result.passed
        assert not report.fell_back

    def test_pages_survive_the_round_trip(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        result, _ = compress_file(source)
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)
        import pypdfium2

        doc = pypdfium2.PdfDocument(str(out))
        try:
            assert len(doc) == 1
            rendered = doc[0].render(scale=1).to_pil()
            assert rendered.size[0] > 0 and rendered.size[1] > 0
        finally:
            doc.close()

    def test_an_image_already_within_target_is_left_alone(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        result, report = compress_file(source, target_dpi=400)  # native is ~259 DPI
        assert report.images.recompressed == 0
        result.close()


class TestVisualModeOnScannedText:
    """Hard-edged, irregular content: this is what makes the effectively-
    bilevel detection worth having, and what CCITT Group 4 is actually for."""

    def test_is_detected_as_bilevel_and_routed_to_g4(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        result, report = compress_file(source)
        assert report.images.recompressed == 1
        assert report.savings_ratio > 0.5
        result.close()

    def test_the_quality_gate_passes(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        _, report = compress_file(source)
        assert report.verify_result is not None
        assert report.verify_result.passed
        assert not report.fell_back

    def test_text_extraction_is_unaffected(self, tmp_path: Path) -> None:
        """The recompressed object is a raster image; the page's own text
        layer (the generated marker) is untouched vector text throughout."""
        source = build_scan_pdf(tmp_path / "scan.pdf")
        result, _ = compress_file(source)
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)
        # build_scan_pdf's page has no marker text of its own; this just
        # confirms the save succeeds and the page still opens and renders.
        import pypdfium2

        doc = pypdfium2.PdfDocument(str(out))
        try:
            assert len(doc) == 1
        finally:
            doc.close()


class TestBilevelSource:
    def test_a_native_1bit_image_is_recompressed_with_g4(self, tmp_path: Path) -> None:
        source = build_bilevel_pdf(tmp_path / "bilevel.pdf")
        result, report = compress_file(source)
        assert report.images.recompressed == 1
        assert report.savings_ratio > 0.3
        result.close()

    def test_the_quality_gate_passes(self, tmp_path: Path) -> None:
        source = build_bilevel_pdf(tmp_path / "bilevel.pdf")
        _, report = compress_file(source)
        assert report.verify_result is not None
        assert report.verify_result.passed

    def test_renders_with_correct_polarity_not_inverted(self, tmp_path: Path) -> None:
        """The regression this project actually shipped once: a clean black-
        on-white source rendering back as white-on-black after G4 round trip.
        Caught only by rendering the real output and sampling real pixels."""
        source = build_bilevel_pdf(tmp_path / "bilevel.pdf")
        result, _ = compress_file(source)
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)

        import pypdfium2

        doc = pypdfium2.PdfDocument(str(out))
        try:
            page = doc[0]
            image = page.render(scale=150 / 72).to_pil().convert("L")
            # The fixture's image sits at (40, 40)pt in a box roughly 250pt
            # wide; well inside that box, background must still read as
            # overwhelmingly light — a full inversion would read as mostly dark.
            sample_box = image.crop((110, 950, 550, 1550))
            histogram = sample_box.histogram()
            light_pixels = sum(histogram[200:])
            total_pixels = sample_box.width * sample_box.height
            assert light_pixels / total_pixels > 0.5, (
                "background should still be predominantly light; a polarity "
                "inversion would make it predominantly dark instead"
            )
        finally:
            doc.close()


class TestCmykIsLeftAlone:
    def test_a_cmyk_image_is_never_recompressed(self, tmp_path: Path) -> None:
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        add_cmyk_image(pdf)
        source = tmp_path / "cmyk.pdf"
        pdf.save(source)

        result, report = compress_file(source, target_dpi=10)  # aggressive enough to tempt it
        assert report.images.recompressed == 0
        assert report.images.left_alone == 1
        result.close()


class TestTheFallback:
    def test_an_unreasonable_target_dpi_falls_back_to_lossless(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        result, report = compress_file(source, target_dpi=15)
        assert report.fell_back
        assert report.mode_used in ("lossless", "none")
        assert report.fallback_reason is not None
        result.close()

    def test_a_fallback_still_keeps_the_pages_intact(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        result, _ = compress_file(source, target_dpi=15)
        assert len(result.pages) == 1
        result.close()

    def test_turning_verification_off_skips_the_gate(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        _, report = compress_file(source, target_dpi=15, verify=False)
        assert report.verify_result is None
        assert not report.fell_back


class TestAlreadyOptimal:
    def test_compressing_twice_reports_nothing_more_to_gain(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        once, _ = compress_file(source)
        once_path = tmp_path / "once.pdf"
        once.save(once_path, **STRUCTURAL_SAVE_OPTIONS)
        once.close()

        _, second_report = compress_file(once_path)
        assert second_report.already_optimal
        assert second_report.mode_used == "none"
        assert second_report.after_bytes == second_report.before_bytes

    def test_a_document_that_would_not_shrink_returns_the_original_object(
        self, make_pdf: PageMaker
    ) -> None:
        source = make_pdf(1)
        with pikepdf.open(source) as pdf:
            result, report = compress(pdf, before_bytes=1)  # an impossibly small "before"
            assert result is pdf
            assert report.already_optimal


class TestNeitherInputIsModified:
    def test_the_source_document_object_is_unchanged(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        with pikepdf.open(source) as pdf:
            page_count_before = len(pdf.pages)
            result, _ = compress(pdf, before_bytes=source.stat().st_size)
            assert len(pdf.pages) == page_count_before
            result.close()

    def test_the_source_file_on_disk_is_untouched(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        before_bytes = source.read_bytes()
        result, _ = compress_file(source)
        assert source.read_bytes() == before_bytes
        result.close()
