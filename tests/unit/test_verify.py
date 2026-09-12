"""Tests for the compression quality gate.

The two fixtures that matter most here are `build_photo_pdf` (genuinely
continuous-tone content) and `build_scan_pdf` (hard-edged, text-shaped
content). The gate has to behave differently on each: a photo tolerates real
resampling noise across the whole page, while text's sharp edges make a naive
worst-single-pixel comparison fail on completely reasonable recompressions —
which is a real failure this project's first version of this file had, caught
only by testing it against text-shaped content and looking at what came back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pikepdf
import pytest
from PIL import Image

from modpdf.verify import verify
from tests.conftest import PageMaker, build_scan_pdf


def resize_and_reencode(pdf_path: Path, *, width_px: int, quality: int) -> pikepdf.Pdf:
    """Downsample the one image on a scan-fixture page and hand back the result
    as an open, in-memory document — the shape every test below needs."""
    with pikepdf.open(pdf_path) as pdf:
        # A dictionary-shaped PDF object supports .values() at runtime;
        # pikepdf's stub for the generic Object base does not say so.
        xobject_dict: Any = pdf.pages[0].obj["/Resources"]["/XObject"]
        xobj = next(iter(xobject_dict.values()))
        pixels = pikepdf.PdfImage(xobj).as_pil_image()
        height_px = round(width_px * pixels.height / pixels.width)
        resized = pixels.resize((width_px, height_px), Image.Resampling.LANCZOS)

        import io

        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=quality)
        xobj.write(buffer.getvalue(), filter=pikepdf.Name("/DCTDecode"))
        xobj.Width = width_px
        xobj.Height = height_px

        out = pikepdf.Pdf.new()
        out.pages.extend(pdf.pages)
        return out


class TestStructuralChecks:
    def test_identical_documents_pass(self, make_pdf: PageMaker) -> None:
        source = make_pdf(3)
        with pikepdf.open(source) as a, pikepdf.open(source) as b:
            result = verify(a, b)
        assert result.passed
        assert result.max_pixel_delta == 0
        assert result.differing_fraction == 0

    def test_a_changed_page_count_fails_immediately(self, make_pdf: PageMaker) -> None:
        source = make_pdf(4)
        with pikepdf.open(source) as original:
            candidate = pikepdf.Pdf.new()
            candidate.pages.extend(original.pages[:2])
            result = verify(original, candidate)
        assert not result.passed
        assert "page count changed" in result.reason
        assert "4" in result.reason and "2" in result.reason

    def test_neither_document_is_modified(self, make_pdf: PageMaker) -> None:
        source = make_pdf(3)
        before = source.read_bytes()
        with pikepdf.open(source) as a, pikepdf.open(source) as b:
            verify(a, b)
        assert source.read_bytes() == before


class TestTextChanges:
    def test_different_text_fails(self, make_pdf: PageMaker) -> None:
        # make_pdf's content is deterministic by page count, not by filename,
        # so two same-length documents from it are textually identical; a real
        # text difference is built by hand instead.
        source = make_pdf(2)
        with pikepdf.open(source) as original:
            candidate = pikepdf.Pdf.new()
            candidate.pages.extend(original.pages)
            # /F1 is the font resource make_pdf's pages already define.
            different_text = b"BT /F1 36 Tf 72 500 Td (Not the same words) Tj ET"
            candidate.pages[0].obj["/Contents"] = candidate.make_stream(different_text)
            result = verify(original, candidate)
        assert not result.passed
        assert "text changed" in result.reason
        candidate.close()

    def test_whitespace_only_differences_are_ignored(self) -> None:
        """A recompress can shift where line breaks fall without moving content."""
        from modpdf.verify import _normalize

        assert _normalize("Hello   World\n\n") == _normalize("Hello World")


class TestVisualChecksOnRealisticContent:
    """The fixture here matters: text is all hard edges, and that is exactly
    what makes a naive comparison unreliable — see the module docstring."""

    def test_a_sensible_downsample_of_text_passes(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        candidate = resize_and_reencode(source, width_px=700, quality=82)
        with pikepdf.open(source) as original:
            result = verify(original, candidate)
        assert result.passed, result.reason
        candidate.close()

    def test_a_destructive_downsample_of_text_fails(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        candidate = resize_and_reencode(source, width_px=90, quality=40)
        with pikepdf.open(source) as original:
            result = verify(original, candidate)
        assert not result.passed
        # Either failure mode is a correct rejection of this much data loss —
        # which one fires is a severity detail, not the behaviour under test.
        assert "visibly" in result.reason or "differs almost completely" in result.reason
        candidate.close()

    def test_the_gate_reports_which_page_was_worst(self, tmp_path: Path) -> None:
        source = build_scan_pdf(tmp_path / "scan.pdf")
        candidate = resize_and_reencode(source, width_px=90, quality=40)
        with pikepdf.open(source) as original:
            result = verify(original, candidate)
        assert result.worst_page == 0
        candidate.close()


class TestASinglePixelCorruptionIsCaughtEvenIfLocalized:
    def test_a_region_gone_fully_wrong_fails_even_if_small(self, make_pdf: PageMaker) -> None:
        """The single-pixel ceiling exists for exactly this: damage too small
        an area to move the whole-page fraction, but total within that area."""
        source = make_pdf(1)
        with pikepdf.open(source) as pdf:
            page = pdf.pages[0]
            # Paint one small black square directly onto the page's content
            # stream — a stand-in for "one image came out completely wrong."
            corrupted_content = (
                page.obj["/Contents"].read_bytes() + b"\n0 0 0 rg 10 10 20 20 re f\n"
            )
            page.obj["/Contents"] = pdf.make_stream(corrupted_content)
            candidate = pikepdf.Pdf.new()
            candidate.pages.extend(pdf.pages)

        with pikepdf.open(source) as original:
            result = verify(original, candidate)
        assert not result.passed
        assert result.max_pixel_delta > 240
        candidate.close()


class TestDoesNotReopenCleanly:
    def test_a_candidate_that_will_not_reopen_fails_with_a_clear_reason(
        self, make_pdf: PageMaker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pypdfium2

        from modpdf import verify as verify_module

        source = make_pdf(2)

        def broken_pdf_document(*args: object, **kwargs: object) -> object:
            raise RuntimeError("simulated: this is not a valid PDF")

        monkeypatch.setattr(pypdfium2, "PdfDocument", broken_pdf_document)
        with pikepdf.open(source) as a, pikepdf.open(source) as b:
            result = verify_module.verify(a, b)
        assert not result.passed
        assert "does not reopen cleanly" in result.reason
