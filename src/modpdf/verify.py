"""Checking that a changed PDF still looks like the document it started as.

This exists for one reason: it is what makes "compress without compromising
quality" a claim that can be checked rather than a promise taken on trust.
Every compressed document is verified against the original before it is
accepted, and `compress` falls back to a lossless result the moment any check
here fails.

Three checks, cheapest and most decisive first:

- **Structural** — the page count has not changed, and the candidate reopens
  cleanly. A document that fails to reopen is not a compressed document.
- **Text** — every page's extracted text is identical, once whitespace
  differences are normalised away. Any drift here means content moved or
  vanished, not that an image got smaller.
- **Visual** — every page is rendered at a fixed resolution and compared
  pixel by pixel. This is what catches an image that technically still shows
  "the same content" but now looks visibly worse.

The visual check does not use a single worst-pixel difference, and that is a
correction rather than the original design: a first version gated on the
single largest per-pixel delta on the page, and it failed on ordinary,
sensible recompressions of scanned text. The reason is that text is all hard
edges, and any resampling shifts an edge by a fraction of a pixel — which
swings a handful of anti-aliased edge pixels from near-white to near-black
even though the page looks identical to a person looking at it. A statistic
built on the single worst pixel is exactly as sensitive to that as it is to
real, widespread degradation, so it cannot tell the two apart.

What actually distinguishes them is *how much of the page* changed, not the
size of the biggest single change. So the gate measures the fraction of
pixels that differ by more than a small per-pixel allowance, and fails only
once that fraction is high enough to mean something changed broadly, not just
at a few edges. A generously high single-pixel ceiling is kept alongside it,
to catch a case where one region — one corrupted image, say — has gone
completely wrong even though it covers little enough of the page that the
fraction alone would not flag it.

Measuring that fraction efficiently over a full-page render is what pulled in
numpy: doing it pixel by pixel in pure Python is too slow to run on every
compress. The project's stated policy was to add numpy only once a concrete
case demanded it; the case this file was built to catch turned out to be it.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pikepdf
import pypdfium2
from PIL import ImageChops

__all__ = ["VerifyResult", "verify"]

# A per-pixel difference at or below this, out of 255, is treated as ordinary
# resampling noise rather than a real change — this is what lets an
# anti-aliased text edge move by a fraction of a pixel without failing a page
# that looks, to a person, identical.
DEFAULT_NOISE_THRESHOLD = 24

# The share of a page's pixels that may differ by more than the noise
# threshold before the page counts as visibly changed. Measured against a
# scanned-text fixture: a sensible 300-to-200-DPI recompression differs on
# about 2.5% of pixels, and a genuinely destructive 300-to-72-DPI crush
# differs on 15% — this sits with real margin on both sides of that gap.
DEFAULT_MAX_DIFFERING_FRACTION = 0.05

# However small the differing area, no single pixel may swing this close to
# a full black/white inversion. This exists for the failure the fraction
# check alone would miss: one small region — a photo, a stamp — that came out
# completely wrong (the wrong colour space decoded, say) while covering too
# little of the page to move the fraction above its own threshold.
DEFAULT_MAX_SINGLE_PIXEL_DELTA = 240

# Rendering at a fixed, modest resolution keeps verification fast on a large
# document while still catching real degradation — a downsampled image looks
# soft at 150 DPI just as clearly as it does at print resolution.
DEFAULT_RENDER_DPI = 150

_WHITESPACE = re.compile(r"\s+")


class VerifyResult:
    """The outcome of comparing a candidate document against its original."""

    __slots__ = ("differing_fraction", "max_pixel_delta", "passed", "reason", "worst_page")

    def __init__(
        self,
        *,
        passed: bool,
        reason: str,
        worst_page: int | None = None,
        max_pixel_delta: int = 0,
        differing_fraction: float = 0.0,
    ) -> None:
        self.passed = passed
        self.reason = reason
        self.worst_page = worst_page
        self.max_pixel_delta = max_pixel_delta
        self.differing_fraction = differing_fraction

    def __repr__(self) -> str:
        return (
            f"VerifyResult(passed={self.passed!r}, reason={self.reason!r}, "
            f"worst_page={self.worst_page!r}, max_pixel_delta={self.max_pixel_delta!r}, "
            f"differing_fraction={self.differing_fraction!r})"
        )


def verify(
    original: pikepdf.Pdf,
    candidate: pikepdf.Pdf,
    *,
    render_dpi: int = DEFAULT_RENDER_DPI,
    noise_threshold: int = DEFAULT_NOISE_THRESHOLD,
    max_differing_fraction: float = DEFAULT_MAX_DIFFERING_FRACTION,
    max_single_pixel_delta: int = DEFAULT_MAX_SINGLE_PIXEL_DELTA,
) -> VerifyResult:
    """Compare `candidate` against `original`. Neither document is modified.

    Both are serialised to memory rather than to a temporary file: pypdfium2
    can render directly from bytes, and a verification pass has no reason to
    touch the filesystem at all.
    """
    if len(original.pages) != len(candidate.pages):
        return VerifyResult(
            passed=False,
            reason=f"page count changed: {len(original.pages)} to {len(candidate.pages)}",
        )

    candidate_bytes = _to_bytes(candidate)
    try:
        reopened = pypdfium2.PdfDocument(io.BytesIO(candidate_bytes))
        reopened.close()
    except Exception as exc:  # pypdfium2 raises a variety of types
        return VerifyResult(passed=False, reason=f"the result does not reopen cleanly: {exc}")

    original_doc = pypdfium2.PdfDocument(io.BytesIO(_to_bytes(original)))
    candidate_doc = pypdfium2.PdfDocument(io.BytesIO(candidate_bytes))
    try:
        worst_page: int | None = None
        worst_fraction = 0.0
        worst_delta = 0

        for index in range(len(original_doc)):
            before_text = _normalize(_page_text(original_doc[index]))
            after_text = _normalize(_page_text(candidate_doc[index]))
            if before_text != after_text:
                return VerifyResult(
                    passed=False, reason=f"page {index + 1}: text changed", worst_page=index
                )

            fraction, delta = _pixel_difference(
                original_doc[index], candidate_doc[index], render_dpi, noise_threshold
            )
            if fraction > worst_fraction:
                worst_fraction, worst_page = fraction, index
            worst_delta = max(worst_delta, delta)

            if delta > max_single_pixel_delta:
                return VerifyResult(
                    passed=False,
                    reason=f"page {index + 1}: a region differs almost completely "
                    f"(peak difference {delta}/255)",
                    worst_page=index,
                    max_pixel_delta=delta,
                    differing_fraction=fraction,
                )
            if fraction > max_differing_fraction:
                return VerifyResult(
                    passed=False,
                    reason=f"page {index + 1}: {fraction * 100:.1f}% of pixels changed "
                    f"visibly, above the {max_differing_fraction * 100:.0f}% limit",
                    worst_page=index,
                    max_pixel_delta=delta,
                    differing_fraction=fraction,
                )

        return VerifyResult(
            passed=True,
            reason="text identical; visual difference within limits",
            worst_page=worst_page,
            max_pixel_delta=worst_delta,
            differing_fraction=worst_fraction,
        )
    finally:
        original_doc.close()
        candidate_doc.close()


def _to_bytes(pdf: pikepdf.Pdf) -> bytes:
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def _page_text(page: pypdfium2.PdfPage) -> str:
    text_page = page.get_textpage()
    try:
        return str(text_page.get_text_range())
    finally:
        text_page.close()


def _normalize(text: str) -> str:
    """Collapse whitespace differences that carry no meaning.

    A recompress can shift exactly where a line break falls in the extracted
    stream without anything actually moving on the page; comparing raw text
    would flag that as content loss. Collapsing every run of whitespace to a
    single space and trimming the ends removes that noise while still catching
    a real change in the words themselves.
    """
    return _WHITESPACE.sub(" ", text).strip()


def _pixel_difference(
    before: pypdfium2.PdfPage, after: pypdfium2.PdfPage, dpi: int, noise_threshold: int
) -> tuple[float, int]:
    """How much of the page changed, and the single largest change on it.

    Returns (fraction of pixels whose worst-channel difference exceeds
    `noise_threshold`, the single largest worst-channel difference on the
    page) — see the module docstring for why both numbers matter.
    """
    scale = dpi / 72
    before_image = before.render(scale=scale).to_pil().convert("RGB")
    after_image = after.render(scale=scale).to_pil().convert("RGB")

    if before_image.size != after_image.size:
        # A page whose rendered dimensions changed has already failed for a
        # more basic reason than a pixel count; report it as maximally
        # different rather than raising out of the comparison below.
        return 1.0, 255

    diff = ImageChops.difference(before_image, after_image)
    worst_per_pixel = np.asarray(diff).max(axis=-1)
    fraction = float((worst_per_pixel > noise_threshold).mean())
    peak = int(worst_per_pixel.max())
    return fraction, peak
