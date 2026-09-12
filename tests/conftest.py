"""Shared test fixtures.

Every PDF the suite touches is generated here, at test time. None are committed.
That is partly hygiene — this is a privacy tool and a stray real document in the
git history would be a bad look — and partly practical: generated pages carry a
known marker, so after a split or a reorder we can extract the text and assert
that page 3 really is the page that started as page 3. Eyeballing a PDF proves
nothing.
"""

from __future__ import annotations

import os

# Set before anything imports `modpdf.cli`: its Rich consoles re-measure the
# terminal on every print, reading these same variables, so a test asserting
# on captured CLI output would otherwise wrap and style differently depending
# on whatever terminal (or lack of one) happens to be running the suite —
# passing locally and failing in CI, or the reverse, for reasons that have
# nothing to do with the code under test. This was a real, confirmed bug:
# GitHub Actions sets FORCE_COLOR for its runners so tool output looks right
# in the Actions log, which styled a `--help` flag's own name in the middle
# ("--password-stdin" split by colour codes into separate runs), and a long
# `tmp_path` wrapped an error message onto two lines mid-sentence — both
# broke a substring assertion on captured output, only on that platform.
#
# NO_COLOR alone does not win: this Rich version gives FORCE_COLOR priority
# over it, so the variable has to be removed outright, not merely overridden.
# A fixed, wide, colourless terminal makes captured output deterministic; it
# has no effect on a real user's actual terminal, which Rich still detects
# normally outside the test suite.
os.environ["COLUMNS"] = "200"
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("CLICOLOR_FORCE", None)

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pikepdf
import pypdfium2
import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

PageMaker = Callable[..., Path]


def marker(page_number: int) -> str:
    """The text stamped on a generated page, and the thing we assert on later."""
    return f"ModPDF test page {page_number}"


def build_pdf(path: Path, page_count: int, *, title: str | None = None) -> Path:
    """Write a PDF whose every page announces which page it started as."""
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    if title:
        pdf.setTitle(title)
    for number in range(1, page_count + 1):
        pdf.setFont("Helvetica", 36)
        pdf.drawString(72, 500, marker(number))
        pdf.showPage()
    pdf.save()
    return path


def page_text(path: Path) -> list[str]:
    """Extract the text of each page, so page identity can be asserted."""
    document = pypdfium2.PdfDocument(path)
    try:
        return [page.get_textpage().get_text_range().strip() for page in document]
    finally:
        document.close()


def page_markers(path: Path) -> list[int]:
    """Which original page numbers a document now contains, in order.

    This is the assertion most operation tests want: ``page_markers(out) == [3, 1, 2]``
    says precisely what a reorder was supposed to do.
    """
    numbers = []
    for text in page_text(path):
        prefix = "ModPDF test page "
        if prefix not in text:
            raise AssertionError(f"page is not a generated test page: {text!r}")
        numbers.append(int(text.split(prefix, 1)[1].split()[0]))
    return numbers


def build_bookmarked_pdf(path: Path, page_count: int) -> Path:
    """A generated PDF with a two-level outline, for testing bookmark survival.

    Every third page starting at page 1 gets a top-level "Chapter" entry; the
    pages between get "Section" entries nested underneath it.
    """
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    for number in range(1, page_count + 1):
        pdf.setFont("Helvetica", 36)
        pdf.drawString(72, 500, marker(number))
        pdf.bookmarkPage(f"page{number}")
        if number % 3 == 1:
            pdf.addOutlineEntry(f"Chapter {number // 3 + 1}", f"page{number}", level=0)
        else:
            pdf.addOutlineEntry(f"Section {number}", f"page{number}", level=1)
        pdf.showPage()
    pdf.save()
    return path


def build_hostile_pdf(path: Path, page_count: int = 3) -> Path:
    """A PDF carrying everything `inspect` is supposed to warn about.

    Real malicious PDFs are not safe to keep in a repository and public samples
    go stale, so we build our own: document-level JavaScript, an /OpenAction, a
    Launch action, a tracking URI, an embedded spreadsheet and an XFA form. The
    payloads are inert — the point is that they are *found*, not that they work.
    """
    base = build_pdf(path.parent / f"{path.stem}-base.pdf", page_count)
    pdf = pikepdf.open(base)

    script = pdf.make_indirect(
        pikepdf.Dictionary(S=pikepdf.Name("/JavaScript"), JS=pikepdf.String("app.alert(1);"))
    )
    pdf.Root["/OpenAction"] = script

    spec = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Filespec"),
            F=pikepdf.String("payroll.xlsx"),
            EF=pikepdf.Dictionary(F=pdf.make_stream(b"inert placeholder bytes")),
        )
    )
    pdf.Root["/Names"] = pdf.make_indirect(
        pikepdf.Dictionary(
            JavaScript=pdf.make_indirect(
                pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("startup"), script]))
            ),
            EmbeddedFiles=pdf.make_indirect(
                pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("payroll.xlsx"), spec]))
            ),
        )
    )

    launch = pdf.make_indirect(
        pikepdf.Dictionary(S=pikepdf.Name("/Launch"), F=pikepdf.String("calc.exe"))
    )
    uri = pdf.make_indirect(
        pikepdf.Dictionary(
            S=pikepdf.Name("/URI"),
            URI=pikepdf.String("http://tracker.example.com/beacon"),
        )
    )
    pdf.pages[0].obj["/Annots"] = pdf.make_indirect(
        pikepdf.Array(
            [
                pdf.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name("/Annot"),
                        Subtype=pikepdf.Name("/Link"),
                        Rect=pikepdf.Array([0, 0, 10, 10]),
                        A=launch,
                    )
                ),
                pdf.make_indirect(
                    pikepdf.Dictionary(
                        Type=pikepdf.Name("/Annot"),
                        Subtype=pikepdf.Name("/Link"),
                        Rect=pikepdf.Array([0, 10, 10, 20]),
                        A=uri,
                    )
                ),
            ]
        )
    )

    pdf.Root["/AcroForm"] = pdf.make_indirect(
        pikepdf.Dictionary(
            XFA=pikepdf.Array([pikepdf.String("template"), pdf.make_stream(b"<xdp:xdp/>")])
        )
    )

    pdf.save(path)
    pdf.close()
    return path


def outline_summary(path: Path) -> list[tuple[int, str, int]]:
    """Flatten a document's outline to (depth, title, 1-based page) triples."""
    summary: list[tuple[int, str, int]] = []
    with pikepdf.open(path) as pdf:
        with pdf.open_outline() as outline:

            def walk(items: list[pikepdf.OutlineItem], depth: int) -> None:
                for item in items:
                    destination: Any = item.destination
                    page = pdf.pages.index(destination[0]) + 1
                    summary.append((depth, str(item.title), page))
                    walk(item.children, depth + 1)

            walk(outline.root, 0)
    return summary


# Placing a fixture's image in a box smaller than the full page raises its
# effective DPI without needing a larger, slower-to-process pixel count — a
# 900x1100px image at 259 DPI takes the same instant to build and compress as
# one at 106 DPI, and 259 clears the default 200 DPI target with real margin.
_SMALL_BOX_PT = (250, 306)


def build_photo_pdf(path: Path, *, width_px: int = 900, height_px: int = 1100) -> Path:
    """A page holding one genuinely photographic image: a smooth gradient plus
    continuous-tone noise, placed at roughly 259 effective DPI.

    This is deliberately not flat colour and not line art. Flate/PNG-style
    compression is very good at large uniform regions and poor at continuous
    tonal variation; JPEG is the other way round. A fixture built from flat
    shapes would make Flate look artificially competitive with JPEG and give
    `compress` nothing honest to test — this is shaped like what a real photo
    or a textured scan actually looks like to a compressor.
    """
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:height_px, 0:width_px]
    gradient = (xx / width_px * 120 + yy / height_px * 80).astype(np.float32)
    noise = rng.normal(0, 8, size=(height_px, width_px)).astype(np.float32)
    base = np.clip(gradient + noise + 60, 0, 255).astype(np.uint8)
    rgb = np.stack(
        [
            base,
            np.clip(base * 0.9 + 20, 0, 255).astype(np.uint8),
            np.clip(base * 1.1, 0, 255).astype(np.uint8),
        ],
        axis=-1,
    )
    image_path = path.with_suffix(".png")
    Image.fromarray(rgb, mode="RGB").save(image_path)

    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.drawImage(str(image_path), x=40, y=40, width=_SMALL_BOX_PT[0], height=_SMALL_BOX_PT[1])
    pdf.showPage()
    pdf.save()
    return path


def build_scan_pdf(
    path: Path, *, width_px: int = 900, height_px: int = 1100, seed: int = 7
) -> Path:
    """A page holding one image shaped like scanned text: many small, sharp,
    irregularly-placed dark rectangles on a light background, at roughly 259
    effective DPI.

    This is what makes the verification gate meaningful to test: text is all
    hard edges, and resampling shifts those edges by a fraction of a pixel,
    which is exactly the failure mode a naive worst-single-pixel comparison
    cannot tell apart from real degradation. A fixture built from soft
    gradients would never exercise that. The same irregularity is also what
    makes this a fair test of whether recompression helps at all: a perfectly
    periodic pattern (a checkerboard, say) compresses so well under plain
    Flate that no recompression can beat it, which says nothing about how
    recompression performs on an actual scanned page.
    """
    from PIL import Image, ImageDraw

    image = Image.new("L", (width_px, height_px), 250)
    draw = ImageDraw.Draw(image)
    rng = __import__("random").Random(seed)
    line_height = max(6, height_px // 55)
    for line_y in range(int(height_px * 0.05), int(height_px * 0.95), line_height * 2):
        x = int(width_px * 0.06)
        limit = int(width_px * 0.92)
        while x < limit:
            run = rng.randint(6, 30)
            draw.rectangle(
                [x, line_y, x + run, line_y + line_height - 2],
                fill=rng.choice([10, 20, 30, 15]),
            )
            x += run + rng.randint(4, 12)

    image_path = path.with_suffix(".png")
    image.convert("RGB").save(image_path)

    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.drawImage(str(image_path), x=40, y=40, width=_SMALL_BOX_PT[0], height=_SMALL_BOX_PT[1])
    pdf.showPage()
    pdf.save()
    return path


def build_bilevel_pdf(
    path: Path, *, width_px: int = 760, height_px: int = 929, seed: int = 11
) -> Path:
    """A page holding one 1-bit image shaped like scanned text, at roughly
    219 effective DPI, for testing CCITT G4 recompression.

    Deliberately irregular strokes rather than a periodic pattern such as a
    checkerboard: a checkerboard's perfect regularity lets plain Flate
    compress it almost as well as a purpose-built codec can, which would make
    G4 look pointless for exactly the reason real scanned text is not
    checkerboard-shaped.
    """
    from PIL import Image, ImageDraw

    image = Image.new("1", (width_px, height_px), 1)
    draw = ImageDraw.Draw(image)
    rng = __import__("random").Random(seed)
    line_height = max(4, height_px // 55)
    for line_y in range(int(height_px * 0.05), int(height_px * 0.95), line_height * 2):
        x = int(width_px * 0.06)
        limit = int(width_px * 0.92)
        while x < limit:
            run = rng.randint(4, 20)
            draw.rectangle([x, line_y, x + run, line_y + line_height - 2], fill=0)
            x += run + rng.randint(3, 8)

    image_path = path.with_suffix(".png")
    image.save(image_path)

    box_width = _SMALL_BOX_PT[0]
    box_height = box_width * height_px / width_px
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.drawImage(str(image_path), x=40, y=40, width=box_width, height=box_height)
    pdf.showPage()
    pdf.save()
    return path


def add_cmyk_image(pdf: pikepdf.Pdf, page_index: int = 0, *, size_px: int = 64) -> pikepdf.Object:
    """Add a CMYK image XObject directly to a page, since reportlab cannot
    emit CMYK images itself. Returns the XObject, already placed on the page.
    """
    import io as _io

    from PIL import Image as _Image

    cmyk = _Image.new("CMYK", (size_px, size_px), (255, 0, 0, 0))
    buffer = _io.BytesIO()
    cmyk.save(buffer, format="JPEG", quality=90)

    page = pdf.pages[page_index]
    xobj = pdf.make_stream(
        buffer.getvalue(),
        Type=pikepdf.Name("/XObject"),
        Subtype=pikepdf.Name("/Image"),
        Width=size_px,
        Height=size_px,
        BitsPerComponent=8,
        ColorSpace=pikepdf.Name("/DeviceCMYK"),
        Filter=pikepdf.Name("/DCTDecode"),
    )
    if "/XObject" not in page.obj["/Resources"]:
        page.obj["/Resources"]["/XObject"] = pdf.make_indirect(pikepdf.Dictionary())
    page.obj["/Resources"]["/XObject"]["/CmykTestImage"] = xobj

    content = b"q 200 0 0 200 100 100 cm /CmykTestImage Do Q\n"
    existing = page.obj.get("/Contents")
    new_stream = pdf.make_stream(content)
    if existing is None:
        page.obj["/Contents"] = new_stream
    else:
        page.obj["/Contents"] = pdf.make_indirect(pikepdf.Array([existing, new_stream]))
    return xobj


@pytest.fixture
def make_pdf(tmp_path: Path) -> PageMaker:
    """Factory fixture: ``make_pdf(5)`` gives a five-page document in tmp_path."""
    counter = 0

    def factory(page_count: int = 3, *, name: str | None = None, title: str | None = None) -> Path:
        nonlocal counter
        counter += 1
        filename = name or f"doc{counter}.pdf"
        return build_pdf(tmp_path / filename, page_count, title=title)

    return factory
