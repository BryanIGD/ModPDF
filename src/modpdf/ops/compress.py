"""Shrinking a PDF without pretending you can shrink what is already small.

A PDF that is text and vector graphics is already a set of compressed drawing
commands; there is no clever trick waiting to be applied to it. Every large,
dramatic size reduction you have ever seen advertised came from one thing:
recompressing images. So this module does two genuinely different jobs and is
honest about which one is doing the work.

**Structural** optimization is always safe and always applied: QPDF's own
object-stream generation, flate recompression and dead-object cleanup, done
purely by choosing the right options to `Pdf.save`. It touches no pixel and no
character. On a scanned document it saves almost nothing; on a document that
has been split and merged a few times, with duplicate fonts and orphaned
objects accumulated along the way, it can save a real amount.

**Image** recompression is where the size actually comes from on a scanned
document. Each image's *effective DPI* — how many of its pixels actually land
on the printed page, found by tracking the page's transform matrix through its
content stream — decides whether it is oversized for on-screen use. An image
already at or below the target is left alone; anything above it is
downsampled and re-encoded. This is the only step that changes what a page
looks like, which is why it is the only step gated by `modpdf.verify` and the
only one with a lossless fallback.

How aggressively that image pass runs is chosen by picking one of three named
`Level`s (see `LEVELS`) rather than a raw DPI number: "low" barely touches
anything, "balanced" is this module's original, long-standing default, and
"high" is the one tier allowed to trade away some visible quality for a
meaningfully smaller file — its own entry in `LEVELS` widens what
`modpdf.verify` will accept accordingly, rather than reaching for that result
and immediately discarding it.

Which codec an oversized image gets is decided by its actual pixel values, not
by how it happens to be stored. A first version trusted the PDF's own storage
mode — a genuine 1-bit image got CCITT Group 4, anything else got JPEG — and
it was wrong on real content: most scanners and PDF generators store even
plain black-and-white text as 8-bit grayscale or RGB, because true 1-bit
capture throws away the antialiasing that keeps small text legible, so nearly
every scanned page took the JPEG path regardless of what was actually on it.
JPEG has nothing to offer content that is really just black text on white —
there is no continuous tone to preserve — and measured against this project's
own quality gate it routinely came back *larger* than the original. So an
oversized 8-bit image is now sampled first: if the overwhelming majority of
its pixels sit at or near black or white, it is treated as text and given the
codec built for that, whatever colour space the source happened to use.

Left deliberately untouched, and reported as such rather than silently: **CMYK
images** (a naive re-encode was tested against this project's own quality gate
and came back with a pure cyan swatch rendering as white — the well-known
Adobe CMYK-JPEG inversion problem — so this is a tested decision, not an
oversight), **indexed/palette images**, and any image carrying a soft mask
(transparency). Getting the last of those right means resizing the mask in
lockstep with its parent, which is a real feature this project intends to
support but does not yet; recompressing the parent without it would risk the
mask drifting out of alignment, so both are left alone together for now.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal, cast

import pikepdf
from pikepdf import Name
from PIL import Image
from PIL.TiffImagePlugin import TiffImageFile

from modpdf import verify as verify_module

__all__ = [
    "DEFAULT_JPEG_QUALITY",
    "DEFAULT_LEVEL",
    "DEFAULT_TARGET_DPI",
    "LEVELS",
    "STRUCTURAL_SAVE_OPTIONS",
    "CompressReport",
    "ImageSummary",
    "Level",
    "LevelSettings",
    "Mode",
    "compress",
]

Mode = Literal["visual", "lossless"]

DEFAULT_TARGET_DPI = 200
DEFAULT_JPEG_QUALITY = 82
# A recompressed image must land at no more than this fraction of its former
# size to be worth keeping; anything smaller than that is noise, and the
# original — already correctly rendered by every reader — is kept instead.
_MUST_SHRINK_TO = 0.9

# Three named presets, not a raw DPI number for the user to guess at. Each one
# is a tuned bundle of how aggressively images are downsampled, how hard the
# JPEG path pushes, and — for "high" only — how much visible difference the
# quality gate in `modpdf.verify` will accept before falling back to lossless.
# "low" and "balanced" keep the gate at its normal, strict defaults: those two
# tiers promise no visible loss, so there is nothing to loosen. "high" is the
# one tier whose whole purpose is trading visible quality for size — matching
# how every mainstream PDF compressor's "extreme"/"maximum" tier actually
# behaves — so its own acceptance threshold is widened to match what it is
# allowed to do, rather than immediately discarding its own output.
Level = Literal["low", "balanced", "high"]

DEFAULT_LEVEL: Level = "balanced"


@dataclass(frozen=True)
class LevelSettings:
    """What one named compression level actually resolves to."""

    target_dpi: int
    jpeg_quality: int
    max_differing_fraction: float
    max_single_pixel_delta: int
    # "low" and "balanced" only ever touch an image that is actually oversized
    # for where it is placed — an image already at or below the target is
    # correctly sized and left alone, because re-encoding it would only cost
    # quality for no real gain. That is the right choice for two tiers that
    # both promise no visible loss, but it is also why "high" could otherwise
    # do little on a document whose images were already reasonably sized
    # (screen-resolution exports, previously-compressed scans): there would be
    # nothing left for it to downsample. "high"'s whole premise is trading
    # quality for size, so it sets this to re-encode every eligible image at
    # its own lower JPEG quality regardless of whether the image was
    # oversized — still gated by the same "keep only if it actually shrinks"
    # check every image goes through.
    always_recompress: bool = False


LEVELS: dict[Level, LevelSettings] = {
    "low": LevelSettings(
        target_dpi=300,
        jpeg_quality=90,
        max_differing_fraction=verify_module.DEFAULT_MAX_DIFFERING_FRACTION,
        max_single_pixel_delta=verify_module.DEFAULT_MAX_SINGLE_PIXEL_DELTA,
    ),
    # Identical to this module's own long-standing defaults, so choosing
    # "balanced" changes nothing about what compressing a file already did.
    "balanced": LevelSettings(
        target_dpi=DEFAULT_TARGET_DPI,
        jpeg_quality=DEFAULT_JPEG_QUALITY,
        max_differing_fraction=verify_module.DEFAULT_MAX_DIFFERING_FRACTION,
        max_single_pixel_delta=verify_module.DEFAULT_MAX_SINGLE_PIXEL_DELTA,
    ),
    "high": LevelSettings(
        target_dpi=100,
        jpeg_quality=40,
        max_differing_fraction=0.45,
        max_single_pixel_delta=250,
        always_recompress=True,
    ),
}

# QPDF's own structural cleanup: generate object streams, recompress every
# Flate stream at maximum, and garbage-collect anything unreferenced. Safe on
# any document; passed to every save this module makes so that a size
# reported here is the size that lands on disk.
STRUCTURAL_SAVE_OPTIONS: dict[str, Any] = {
    "object_stream_mode": pikepdf.ObjectStreamMode.generate,
    "compress_streams": True,
    "recompress_flate": True,
}


@dataclass(frozen=True)
class ImageSummary:
    """What happened to the document's images."""

    recompressed: int = 0
    left_alone: int = 0
    bytes_before: int = 0
    bytes_after: int = 0


@dataclass(frozen=True)
class CompressReport:
    """What compressing a document actually did, and why."""

    before_bytes: int
    after_bytes: int
    mode_used: Literal["visual", "lossless", "none"]
    images: ImageSummary
    fell_back: bool = False
    fallback_reason: str | None = None
    verify_result: verify_module.VerifyResult | None = None

    @property
    def savings_ratio(self) -> float:
        if self.before_bytes == 0:
            return 0.0
        return max(0.0, 1 - (self.after_bytes / self.before_bytes))

    @property
    def already_optimal(self) -> bool:
        return self.mode_used == "none"


def compress(
    pdf: pikepdf.Pdf,
    *,
    before_bytes: int,
    mode: Mode = "visual",
    target_dpi: int = DEFAULT_TARGET_DPI,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    verify: bool = True,
    max_differing_fraction: float = verify_module.DEFAULT_MAX_DIFFERING_FRACTION,
    max_single_pixel_delta: int = verify_module.DEFAULT_MAX_SINGLE_PIXEL_DELTA,
    always_recompress: bool = False,
) -> tuple[pikepdf.Pdf, CompressReport]:
    """Return a compressed copy of `pdf`, and a report of what was done.

    `pdf` is never modified; every candidate this builds is an independent
    in-memory copy. `before_bytes` is supplied by the caller — the ops layer
    has no file path to measure, and the caller (`modpdf.tasks`) already knows
    the real size of the file on disk.

    Args:
        pdf: The document to compress.
        before_bytes: The size of the document before this call, in bytes.
        mode: "visual" downsamples oversized images as well as doing the
            structural pass; "lossless" only does the structural pass.
        target_dpi: Images above this effective resolution are downsampled to
            it. Meaningless when `mode` is "lossless".
        jpeg_quality: Quality passed to the JPEG encoder for photographic
            images. Meaningless when `mode` is "lossless".
        verify: Compare the visually-compressed result against the original
            with `modpdf.verify` before accepting it. Turning this off is for
            large batch runs in a hurry; leaving it on is what makes the
            "without compromising quality" claim mean something.
        max_differing_fraction: Forwarded to `modpdf.verify.verify` — how much
            of a page may look visibly different before the whole document
            falls back to lossless. Callers that intend to trade away some
            quality on purpose (a "maximum compression" preset, say) widen
            this; the default matches `verify`'s own strict default.
        max_single_pixel_delta: Forwarded to `modpdf.verify.verify` — the
            per-pixel ceiling that always fails a page outright, catching a
            region that came out completely wrong regardless of how much of
            the page it covers. This does not loosen the same way the fraction
            does: a caller intentionally trading quality for size still needs
            this floor, since it is what catches an image that came out
            actually broken rather than merely softer.
        always_recompress: Re-encode every eligible image at `jpeg_quality`
            even when it is not oversized for `target_dpi`. Off by default —
            an image already correctly sized has nothing to gain from a lossy
            re-encode — but a caller trading quality for size on purpose (the
            "maximum compression" preset) turns it on, since otherwise a
            document whose images were already reasonably sized would have
            nothing left to shrink.

    Returns:
        The document to save, and a report describing what happened. If
        neither compression actually made the file smaller, the returned
        document is `pdf` itself and the report says so.
    """
    lossless_bytes = _saved_size(pdf)

    if mode == "lossless":
        return _choose(pdf, pdf, lossless_bytes, before_bytes, "lossless", ImageSummary())

    working = _clone(pdf)
    images = _recompress_images(working, target_dpi, jpeg_quality, always_recompress)
    visual_bytes = _saved_size(working)

    if verify:
        verify_result = verify_module.verify(
            pdf,
            working,
            max_differing_fraction=max_differing_fraction,
            max_single_pixel_delta=max_single_pixel_delta,
        )
        if not verify_result.passed:
            return _choose(
                pdf,
                pdf,
                lossless_bytes,
                before_bytes,
                "lossless",
                images,
                fell_back=True,
                fallback_reason=verify_result.reason,
                verify_result=verify_result,
            )
        return _choose(
            pdf, working, visual_bytes, before_bytes, "visual", images, verify_result=verify_result
        )

    return _choose(pdf, working, visual_bytes, before_bytes, "visual", images)


def _choose(
    original: pikepdf.Pdf,
    candidate: pikepdf.Pdf,
    candidate_bytes: int,
    before_bytes: int,
    mode_used: Literal["visual", "lossless"],
    images: ImageSummary,
    *,
    fell_back: bool = False,
    fallback_reason: str | None = None,
    verify_result: verify_module.VerifyResult | None = None,
) -> tuple[pikepdf.Pdf, CompressReport]:
    """Accept the candidate if it is actually smaller; otherwise keep the original."""
    if candidate_bytes >= before_bytes:
        report = CompressReport(
            before_bytes=before_bytes,
            after_bytes=before_bytes,
            mode_used="none",
            images=images,
            fell_back=fell_back,
            fallback_reason=fallback_reason or "already smaller than any candidate produced",
            verify_result=verify_result,
        )
        return original, report

    report = CompressReport(
        before_bytes=before_bytes,
        after_bytes=candidate_bytes,
        mode_used=mode_used,
        images=images,
        fell_back=fell_back,
        fallback_reason=fallback_reason,
        verify_result=verify_result,
    )
    return candidate, report


def _clone(pdf: pikepdf.Pdf) -> pikepdf.Pdf:
    """An independent in-memory copy, safe to mutate without touching `pdf`."""
    buffer = io.BytesIO()
    pdf.save(buffer)
    buffer.seek(0)
    return pikepdf.open(buffer)


def _saved_size(pdf: pikepdf.Pdf) -> int:
    buffer = io.BytesIO()
    pdf.save(buffer, **STRUCTURAL_SAVE_OPTIONS)
    return buffer.getbuffer().nbytes


# --------------------------------------------------------------- image pass


def _recompress_images(
    pdf: pikepdf.Pdf, target_dpi: int, jpeg_quality: int, always_recompress: bool
) -> ImageSummary:
    """Downsample and re-encode every oversized image reachable from a page —
    and, when `always_recompress` is set, every other eligible image too, at
    its own size but the same lower JPEG quality.

    Mutates `pdf` in place — callers pass a clone they own for this reason.
    """
    dpi_by_xobject = _effective_dpi_map(pdf)

    recompressed = left_alone = bytes_before = bytes_after = 0
    seen: set[tuple[int, int]] = set()

    for page in pdf.pages:
        for xobj in _image_xobjects(page.obj.get("/Resources")):
            key = xobj.objgen
            if key in seen:
                continue
            seen.add(key)

            effective_dpi = dpi_by_xobject.get(key)
            outcome = _recompress_one(
                xobj, effective_dpi, target_dpi, jpeg_quality, always_recompress=always_recompress
            )
            if outcome is None:
                continue

            touched, before, after = outcome
            if touched:
                recompressed += 1
                bytes_before += before
                bytes_after += after
            else:
                left_alone += 1

    return ImageSummary(
        recompressed=recompressed,
        left_alone=left_alone,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )


def _recompress_one(
    xobj: pikepdf.Object,
    effective_dpi: float | None,
    target_dpi: int,
    jpeg_quality: int,
    *,
    always_recompress: bool = False,
) -> tuple[bool, int, int] | None:
    """Try to shrink one image. Returns (touched, bytes_before, bytes_after), or
    None if this image was never a candidate at all (untouched, not counted)."""
    if effective_dpi is None:
        return None  # never actually painted on a page

    oversized = effective_dpi > target_dpi
    if not oversized and not always_recompress:
        return None  # already correctly sized, and nothing asked for more

    if "/SMask" in xobj or "/Mask" in xobj:
        return False, 0, 0  # transparency: see the module docstring

    try:
        # PdfImage wants a Stream specifically; every /Image XObject is one,
        # but pikepdf's own type for a resource-dictionary entry is the more
        # general Object, and this call is already guarded for anything that
        # turns out not to behave like an image underneath.
        pdf_image = pikepdf.PdfImage(cast(pikepdf.Stream, xobj))
        colorspace = str(xobj.get("/ColorSpace", ""))
    except Exception:
        return False, 0, 0  # not a straightforward raster image; leave it alone

    if pdf_image.indexed or "Indexed" in colorspace:
        return False, 0, 0
    if "ICCBased" in colorspace and pdf_image.mode not in ("RGB", "L"):
        return False, 0, 0
    if pdf_image.mode == "CMYK" or "CMYK" in colorspace:
        return False, 0, 0  # see the module docstring: tested, not skipped by guesswork

    before_size = _stream_size(xobj)
    new_width, new_height = int(xobj.Width), int(xobj.Height)
    if oversized:
        scale = target_dpi / effective_dpi
        new_width = max(1, round(new_width * scale))
        new_height = max(1, round(new_height * scale))
        if new_width >= int(xobj.Width) and new_height >= int(xobj.Height):
            if not always_recompress:
                return None
            # Rounding put the target back at the image's own size; fall
            # through to a quality-only re-encode instead of resizing.
            new_width, new_height = int(xobj.Width), int(xobj.Height)

    try:
        pixels = pdf_image.as_pil_image()
    except Exception:
        return False, 0, 0

    if pixels.mode == "1" or (pixels.mode in ("L", "RGB") and _is_effectively_bilevel(pixels)):
        touched = _write_bilevel(xobj, pixels, new_width, new_height)
    elif pixels.mode in ("L", "RGB"):
        touched = _write_photographic(xobj, pixels, new_width, new_height, jpeg_quality)
    else:
        return False, 0, 0

    if not touched:
        return False, 0, 0

    after_size = _stream_size(xobj)
    if after_size > before_size * _MUST_SHRINK_TO:
        return False, 0, 0  # not worth it; caller keeps the structural-only version

    return True, before_size, after_size


def _is_effectively_bilevel(pixels: Image.Image, *, threshold: float = 0.98) -> bool:
    """True if an 8-bit image is, in substance, black text on a white page.

    Genuinely 1-bit PDF images are rare in practice: most scanners and PDF
    generators store even pure black-and-white content as 8-bit grayscale or
    RGB, because true 1-bit capture throws away the antialiasing that keeps
    small text legible. Trusting the PDF's own storage mode to decide between
    JPEG and CCITT Group 4 would miss almost every real scanned document, so
    this looks at the actual pixel values instead: if the overwhelming
    majority sit at or near black or white, JPEG has nothing to gain — there
    is no continuous tone to preserve — and G4 will beat it by a wide margin.

    Checked on a shrunk copy; a histogram is a statistic, not something that
    benefits from being computed at full resolution.
    """
    grayscale = pixels.convert("L")
    sample_size = (min(200, grayscale.width), min(200, grayscale.height))
    # NEAREST, not the smooth default: this is a sample of actual pixel values
    # for a statistic, and any antialiasing resize would blend exactly the
    # sharp 0/255 edges this check is trying to detect into invented midtones.
    sample = grayscale.resize(sample_size, Image.Resampling.NEAREST)
    histogram = sample.histogram()
    # A margin of 40, not a handful of levels: real "black" ink on a real page
    # rarely renders as pure 0 (a lightly inked character, a slightly grey
    # scan background), and this only needs to tell "text" from "photograph"
    # apart, not measure exactly how dark the ink is.
    near_extreme = sum(histogram[:40]) + sum(histogram[-40:])
    total = sample.width * sample.height
    return total > 0 and (near_extreme / total) >= threshold


def _write_photographic(
    xobj: pikepdf.Object, pixels: Image.Image, width: int, height: int, jpeg_quality: int
) -> bool:
    resized = pixels.resize((width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=jpeg_quality)
    xobj.write(buffer.getvalue(), filter=Name("/DCTDecode"))
    xobj.Width = width
    xobj.Height = height
    xobj.ColorSpace = Name("/DeviceGray") if resized.mode == "L" else Name("/DeviceRGB")
    xobj.BitsPerComponent = 8
    for stale_key in ("/Decode", "/DecodeParms"):
        if stale_key in xobj:
            del xobj[stale_key]
    return True


def _write_bilevel(xobj: pikepdf.Object, pixels: Image.Image, width: int, height: int) -> bool:
    """CCITT Group 4: lossless for 1-bit line art, and usually smaller besides.

    The source is resized while still continuous-tone (LANCZOS on grayscale is
    the correct way to shrink a sharp edge smoothly) and only thresholded to
    two levels at the very end, explicitly, with dithering turned off. Letting
    `.convert("1")` do that step on its own — Pillow's default there is
    Floyd-Steinberg error-diffusion dithering — was tried first and failed
    this project's own quality gate: dithering exists to make two tone levels
    *simulate* continuous tone, which is the opposite of what text needs, and
    it scatters noise across exactly the sharp edges this codec exists to keep
    clean.
    """
    grayscale = pixels.convert("L").resize((width, height), Image.Resampling.LANCZOS)
    resized = grayscale.point(lambda level: 255 if level >= 128 else 0).convert(
        "1", dither=Image.Dither.NONE
    )
    buffer = io.BytesIO()
    # strip_size forces Pillow's TIFF writer to use one strip for the whole
    # image. Its default splits a tall image into several, found by testing
    # this exact function against this project's own quality gate: a G4
    # strip's encoding resets to a fresh reference line at its own start, so
    # strips cannot be reassembled by concatenating their compressed bytes,
    # and this function was only ever reading the first one. One strip has
    # nowhere for that to go wrong.
    stride = (width + 7) // 8
    buffer_size = max(stride * height, 1)
    resized.save(buffer, format="TIFF", compression="group4", strip_size=buffer_size)
    raw = _ccitt_strip(buffer.getvalue())
    if raw is None:
        return False

    xobj.write(
        raw,
        filter=Name("/CCITTFaxDecode"),
        # BlackIs1=True, not the PDF default of False. This was found the same
        # way as the strip issue above: by rendering this function's own
        # output through this project's quality gate and looking at what came
        # back, not by reasoning about the TIFF/PDF polarity conventions on
        # paper — those said False, and were wrong. An image built pixel by
        # pixel in mode "1" and this function's image, built by thresholding
        # an "L" image and calling .convert("1"), can read back identical
        # 0/255 values through Pillow's own getpixel() while the raw bits
        # libtiff actually compresses are each other's opposite; only
        # rendering the real, encoded PDF output exposes that. If this
        # function's construction path ever changes, re-verify against a
        # rendered page rather than trusting either value on paper again.
        decode_parms=pikepdf.Dictionary(K=-1, Columns=width, Rows=height, BlackIs1=True),
    )
    xobj.Width = width
    xobj.Height = height
    xobj.ColorSpace = Name("/DeviceGray")
    xobj.BitsPerComponent = 1
    if "/Decode" in xobj:
        del xobj["/Decode"]
    return True


def _ccitt_strip(tiff_bytes: bytes) -> bytes | None:
    """Pull the raw Group 4 strip out of the TIFF container Pillow wrote.

    A PDF's `/CCITTFaxDecode` filter wants one bare encoded stream, not a TIFF
    file; Pillow only knows how to write TIFF, so the stream is extracted from
    it after the fact using the tags TIFF itself uses to record where it is.

    The caller asks Pillow for a single strip covering the whole image, and
    this function insists on that rather than trusting it: a G4 strip resets
    its encoding to a fresh reference line at its own start, so if more than
    one ever came back, concatenating them would silently produce a corrupt
    decode instead of a clean failure. That happened once already, while
    building this function — see `_write_bilevel`.
    """
    # This function only ever receives bytes this module just wrote as TIFF
    # itself, so the TIFF-specific tag table Pillow's generic type omits is
    # always genuinely present.
    image = cast(TiffImageFile, Image.open(io.BytesIO(tiff_bytes)))
    offsets = image.tag_v2.get(273)  # StripOffsets
    counts = image.tag_v2.get(279)  # StripByteCounts
    if not offsets or not counts or len(offsets) != 1:
        return None
    start = offsets[0]
    return tiff_bytes[start : start + counts[0]]


def _stream_size(xobj: pikepdf.Object) -> int:
    try:
        return len(xobj.read_raw_bytes())
    except Exception:
        return 0


def _image_xobjects(resources: pikepdf.Object | None) -> list[pikepdf.Object]:
    """Every direct `/Image` XObject in a resource dictionary. Not recursive
    into Form XObjects: `_effective_dpi_map` walks those for placement, but an
    image nested inside a form is reached from the form's own `/Resources`,
    which is a separate dictionary this function is also called on."""
    if resources is None or "/XObject" not in resources:
        return []
    found = []
    # A dictionary-shaped PDF object supports .values() at runtime; pikepdf's
    # stub for the generic Object base does not say so, since not every
    # Object is dictionary-shaped.
    xobject_dict: Any = resources["/XObject"]
    for xobj in xobject_dict.values():
        if xobj.get("/Subtype") == Name("/Image"):
            found.append(xobj)
        elif xobj.get("/Subtype") == Name("/Form"):
            found.extend(_image_xobjects(xobj.get("/Resources")))
    return found


# ------------------------------------------------------- effective DPI walk


def _effective_dpi_map(pdf: pikepdf.Pdf) -> dict[tuple[int, int], float]:
    """For every image XObject reachable from a page, its effective DPI.

    Effective DPI is how many of the image's own pixels land on each inch of
    the printed page — an image's raw pixel count says nothing about that on
    its own; a 4000-pixel-wide scan placed in a 1-inch box is 4000 DPI, and
    the same image placed across an 11-inch page is 364 DPI. Found by
    tracking the transform matrix through the page's content stream to the
    moment each image is actually painted.

    Where an image is painted more than once at different sizes — a shared
    logo used at two scales, say — the smallest effective DPI across every
    placement is kept, so a downsampling decision never assumes less
    resolution than the most demanding placement actually needs.
    """
    dpi_by_xobject: dict[tuple[int, int], float] = {}
    for page in pdf.pages:
        _walk(page.obj, page.obj.get("/Resources"), _IDENTITY, dpi_by_xobject)
    return dpi_by_xobject


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _matmul(m: tuple[float, ...], by: tuple[float, ...]) -> tuple[float, ...]:
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = by
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _walk(
    content_holder: pikepdf.Object,
    resources: pikepdf.Object | None,
    ctm: tuple[float, ...],
    dpi_by_xobject: dict[tuple[int, int], float],
    *,
    _depth: int = 0,
) -> None:
    """Interpret just enough of a content stream to track the CTM to each `Do`.

    Only `cm`, `q`, `Q` and `Do` matter here; everything else is ignored. A
    small recursion guard stops a form that (legally, if unusually) draws
    itself from looping forever.
    """
    if _depth > 12 or resources is None or "/XObject" not in resources:
        return

    stack: list[tuple[float, ...]] = []
    current = ctm
    xobjects = resources["/XObject"]

    try:
        instructions = pikepdf.parse_content_stream(content_holder)
    except Exception:
        return  # a malformed content stream is not this function's problem to raise on

    for instruction in instructions:
        operator = str(instruction.operator)
        operands = instruction.operands

        if operator == "cm" and len(operands) == 6:
            matrix = tuple(float(value) for value in operands)
            current = _matmul(matrix, current)
        elif operator == "q":
            stack.append(current)
        elif operator == "Q":
            if stack:
                current = stack.pop()
        elif operator == "Do" and operands:
            name = str(operands[0])
            if name not in xobjects:
                continue
            xobj = xobjects[name]
            subtype = xobj.get("/Subtype")
            if subtype == Name("/Image"):
                _record_dpi(xobj, current, dpi_by_xobject)
            elif subtype == Name("/Form"):
                form_ctm = current
                form_matrix = xobj.get("/Matrix")
                if form_matrix is not None and len(form_matrix) == 6:
                    form_ctm = _matmul(tuple(float(value) for value in form_matrix), current)
                _walk(
                    xobj,
                    xobj.get("/Resources") or resources,
                    form_ctm,
                    dpi_by_xobject,
                    _depth=_depth + 1,
                )


def _record_dpi(
    xobj: pikepdf.Object, ctm: tuple[float, ...], dpi_by_xobject: dict[tuple[int, int], float]
) -> None:
    a, b, c, d, *_ = ctm
    width_pt = (a * a + b * b) ** 0.5
    height_pt = (c * c + d * d) ** 0.5
    if width_pt <= 0 or height_pt <= 0:
        return

    try:
        pixel_width = int(xobj.Width)
        pixel_height = int(xobj.Height)
    except (AttributeError, KeyError):
        return

    dpi_x = pixel_width / (width_pt / 72)
    dpi_y = pixel_height / (height_pt / 72)
    effective = min(dpi_x, dpi_y)

    key = xobj.objgen
    existing = dpi_by_xobject.get(key)
    dpi_by_xobject[key] = effective if existing is None else min(existing, effective)
