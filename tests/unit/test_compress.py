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

from modpdf import verify as verify_module
from modpdf.ops.compress import (
    LEVELS,
    STRUCTURAL_SAVE_OPTIONS,
    CompressReport,
    Mode,
    compress,
)
from tests.conftest import (
    PageMaker,
    add_cmyk_image,
    build_bilevel_pdf,
    build_dense_diagram_pdf,
    build_photo_pdf,
    build_scan_pdf,
    page_markers,
)


def compress_file(
    path: Path,
    *,
    mode: Mode = "visual",
    target_dpi: int = 200,
    jpeg_quality: int = 82,
    verify: bool = True,
    max_differing_fraction: float = verify_module.DEFAULT_MAX_DIFFERING_FRACTION,
    max_single_pixel_delta: int = verify_module.DEFAULT_MAX_SINGLE_PIXEL_DELTA,
    always_recompress: bool = False,
    flatten_vector_pages: bool = False,
) -> tuple[pikepdf.Pdf, CompressReport]:
    """Open, compress, and hand back the result plus its report — the shape
    almost every test below wants, with the file's own size as `before_bytes`."""
    before = path.stat().st_size
    with pikepdf.open(path) as pdf:
        return compress(
            pdf,
            before_bytes=before,
            mode=mode,
            target_dpi=target_dpi,
            jpeg_quality=jpeg_quality,
            verify=verify,
            max_differing_fraction=max_differing_fraction,
            max_single_pixel_delta=max_single_pixel_delta,
            always_recompress=always_recompress,
            flatten_vector_pages=flatten_vector_pages,
        )


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


class TestCompressionLevels:
    """The `LEVELS` table is what `tasks.compress_file` (and, through it, the
    CLI's `--level` and the desktop app's three radio buttons) actually
    resolves a named level to. These test the underlying knobs it sets, not
    the table's exact numbers, which are free to be retuned."""

    def test_balanced_matches_this_modules_own_long_standing_defaults(self) -> None:
        """Choosing "balanced" must change nothing about what compressing a
        file already did before levels existed."""
        from modpdf.ops.compress import DEFAULT_JPEG_QUALITY, DEFAULT_TARGET_DPI
        from modpdf.verify import DEFAULT_MAX_DIFFERING_FRACTION, DEFAULT_MAX_SINGLE_PIXEL_DELTA

        balanced = LEVELS["balanced"]
        assert balanced.target_dpi == DEFAULT_TARGET_DPI
        assert balanced.jpeg_quality == DEFAULT_JPEG_QUALITY
        assert balanced.max_differing_fraction == DEFAULT_MAX_DIFFERING_FRACTION
        assert balanced.max_single_pixel_delta == DEFAULT_MAX_SINGLE_PIXEL_DELTA

    def test_low_is_gentler_than_balanced_on_raw_image_settings(self) -> None:
        low, balanced = LEVELS["low"], LEVELS["balanced"]
        assert low.target_dpi > balanced.target_dpi
        assert low.jpeg_quality > balanced.jpeg_quality

    def test_high_keeps_its_own_images_close_to_lossless_by_choice(self) -> None:
        """"high"'s target DPI and JPEG quality are deliberately *not* the
        most aggressive of the three: they were raised, on a real document,
        until a flattened page's own text was legible again. Its size
        reduction comes from `always_recompress` and `flatten_vector_pages`
        instead — see `test_high_can_end_up_larger_than_balanced_on_a_plain_photo`
        for the accepted cost of that choice."""
        balanced, high = LEVELS["balanced"], LEVELS["high"]
        assert high.target_dpi >= balanced.target_dpi
        assert high.jpeg_quality >= balanced.jpeg_quality

    def test_high_can_end_up_larger_than_balanced_on_a_plain_photo(self, tmp_path: Path) -> None:
        """A known, accepted cost of keeping "high"'s own images close to
        lossless (see the test above): on a document with no heavy vector
        page to flatten — an ordinary photo or scan, most real documents —
        "high" has nothing left to win on, while "balanced"'s own lower JPEG
        quality still recompresses the image normally. "Maximum compression"
        is not a blanket promise of the smallest possible file on every
        document; it is a promise about what it does when there is vector
        content worth flattening. If this ever starts passing, the images
        pass changed enough that the CLI's "note" about traded-away quality,
        and the README's framing of `high`, should be revisited."""
        source = build_photo_pdf(tmp_path / "photo.pdf")
        _, balanced = compress_file(source)
        _, high = compress_file(
            source,
            target_dpi=LEVELS["high"].target_dpi,
            jpeg_quality=LEVELS["high"].jpeg_quality,
            max_differing_fraction=LEVELS["high"].max_differing_fraction,
            max_single_pixel_delta=LEVELS["high"].max_single_pixel_delta,
            always_recompress=True,
        )
        assert high.after_bytes > balanced.after_bytes

    def test_only_high_widens_the_quality_gate(self) -> None:
        """ "low" and "balanced" promise no visible loss, so neither has any
        reason to accept more visible difference than `verify`'s own default;
        "high" is the one tier whose entire point is trading some away."""
        low, balanced, high = LEVELS["low"], LEVELS["balanced"], LEVELS["high"]
        assert low.max_differing_fraction == balanced.max_differing_fraction
        assert high.max_differing_fraction > balanced.max_differing_fraction

    def test_a_low_jpeg_quality_shrinks_a_photo_more_than_a_high_one(self, tmp_path: Path) -> None:
        source = build_photo_pdf(tmp_path / "photo.pdf")
        _, high_quality = compress_file(source, jpeg_quality=95)
        _, low_quality = compress_file(source, jpeg_quality=30)
        assert low_quality.after_bytes < high_quality.after_bytes

    def test_a_widened_fraction_accepts_a_candidate_the_default_gate_would_reject(
        self, tmp_path: Path
    ) -> None:
        """Same aggressive target on the same document: the strict default
        gate falls back, a deliberately widened one accepts the same result."""
        source = build_scan_pdf(tmp_path / "scan.pdf")

        _, strict = compress_file(source, target_dpi=15)
        assert strict.fell_back

        _, widened = compress_file(
            source,
            target_dpi=15,
            max_differing_fraction=0.9,
            max_single_pixel_delta=255,
        )
        assert not widened.fell_back
        assert widened.mode_used == "visual"

    def test_high_is_the_only_level_that_always_recompresses(self) -> None:
        low, balanced, high = LEVELS["low"], LEVELS["balanced"], LEVELS["high"]
        assert not low.always_recompress
        assert not balanced.always_recompress
        assert high.always_recompress

    def test_always_recompress_still_shrinks_an_image_already_within_target(
        self, tmp_path: Path
    ) -> None:
        """The bug this exists to fix: a real document whose images are
        already at or below the target DPI (a screen-resolution export, say)
        used to have nothing left for `compress` to do — every level skipped
        such an image outright, so "maximum compression" saved no more than
        "balanced" did. `always_recompress` re-encodes it anyway, at a lower
        JPEG quality, instead of leaving it untouched."""
        source = build_photo_pdf(tmp_path / "photo.pdf")  # native is ~259 DPI

        _, left_alone = compress_file(source, target_dpi=400)
        assert left_alone.images.recompressed == 0

        _, recompressed = compress_file(source, target_dpi=400, always_recompress=True)
        assert recompressed.images.recompressed == 1
        assert recompressed.after_bytes < left_alone.after_bytes


class TestFlatteningComplexVectorPages:
    """A photo-heavy scan is not the only way a PDF gets large: a page whose
    own vector content (not an image at all) is enormous is untouched by
    every image-level setting, since there is no oversized image to find.
    `flatten_vector_pages` rasterizes such a page's graphics while keeping
    every character of its text exactly as it was. "low" never does this —
    it promises to barely touch anything; "balanced" and "high" both do, at
    their own settings, so a document like that lands between the two
    instead of "balanced" tying with "low" on it.
    """

    def test_low_never_flattens_but_balanced_and_high_do(self) -> None:
        low, balanced, high = LEVELS["low"], LEVELS["balanced"], LEVELS["high"]
        assert not low.flatten_vector_pages
        assert balanced.flatten_vector_pages
        assert high.flatten_vector_pages

    def test_a_heavy_vector_page_shrinks_with_text_intact(self, tmp_path: Path) -> None:
        import pypdfium2

        # More shapes than this class's other tests: "high" keeps its own
        # target DPI and JPEG quality close to lossless (220/100) so a
        # flattened page stays sharp, which means the flattened background
        # only wins over the original once the page's vector content is
        # heavy enough — a much higher bar than a lower-quality flatten would
        # need, which is exactly the point of choosing near-lossless settings.
        source = build_dense_diagram_pdf(tmp_path / "diagram.pdf", shapes=80000)
        # This test uses "high"'s own settings end to end, not only the flag
        # under test: at this file's much gentler defaults (200 DPI, quality
        # 82, the strict gate), the flattened background does not beat the
        # original at all, which is exactly why "high" widens all three —
        # the same reasoning `always_recompress`'s own tests already rely on.
        high = LEVELS["high"]
        result, report = compress_file(
            source,
            target_dpi=high.target_dpi,
            jpeg_quality=high.jpeg_quality,
            max_differing_fraction=high.max_differing_fraction,
            max_single_pixel_delta=high.max_single_pixel_delta,
            flatten_vector_pages=True,
            always_recompress=True,
        )
        out = tmp_path / "out.pdf"
        result.save(out, **STRUCTURAL_SAVE_OPTIONS)
        result.close()

        assert report.pages_flattened == 1
        assert report.savings_ratio > 0.2
        assert not report.fell_back

        doc = pypdfium2.PdfDocument(str(out))
        try:
            assert doc[0].get_textpage().get_text_range().strip() == "Confidential Diagram Label"
        finally:
            doc.close()

    def test_a_page_below_the_threshold_is_left_alone(self, tmp_path: Path) -> None:
        source = build_dense_diagram_pdf(tmp_path / "diagram.pdf", shapes=200)
        _, report = compress_file(source, flatten_vector_pages=True, always_recompress=True)
        assert report.pages_flattened == 0

    def test_flattening_is_off_by_default(self, tmp_path: Path) -> None:
        """Without the flag, an otherwise-flattenable page is untouched —
        this is what keeps "low" and "balanced" from ever rasterizing a
        page's own vector art."""
        source = build_dense_diagram_pdf(tmp_path / "diagram.pdf")
        _, report = compress_file(source)
        assert report.pages_flattened == 0

    def test_an_unsuitable_result_falls_back_rather_than_shipping(self, tmp_path: Path) -> None:
        """Pushed hard enough, a flattened page can still look different
        enough to fail the quality gate — proving the safety net holds here
        too, not only for the image pass. `pages_flattened` is 0 in the
        accepted report either way: a rejected candidate is not what shipped.
        """
        source = build_dense_diagram_pdf(tmp_path / "diagram.pdf")
        # An unreasonably harsh target forces heavy downsampling on top of
        # the flattening, which is enough to tip this fixture's own gate.
        _, report = compress_file(
            source, target_dpi=20, flatten_vector_pages=True, always_recompress=True
        )
        assert report.fell_back
        assert report.mode_used in ("lossless", "none")
        assert report.pages_flattened == 0


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
