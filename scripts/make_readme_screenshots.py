"""Regenerate the screenshots in docs/images/ used by the README.

    .venv/bin/python scripts/make_readme_screenshots.py

Builds a fictional sample document, opens it in the real desktop app with Qt's
offscreen platform (no display needed), and saves what the window draws. Run it
again after changing the UI so the README never shows an older version of the
app than the one in the repo.

The sample is generated rather than committed, like every PDF in the test
suite: this project never checks a real document into git.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
SLATE, BLUE, MIST = HexColor("#2E3742"), HexColor("#5B82B0"), HexColor("#E7EDF5")

PARAGRAPH = (
    "The terminal replaces the 1968 ferry building with a two-storey hall that "
    "keeps foot passengers and vehicle lanes apart. Boarding moves to the east "
    "berth, and the old waiting room becomes covered bicycle parking."
)


def _photo(seed: int, width: int = 2400, height: int = 1600) -> Image.Image:
    """A soft landscape: sky, water, a headland. Large on purpose, so the
    compression screenshot has an oversized image to downsample."""
    rng = np.random.default_rng(seed)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    horizon = int(height * 0.58)
    for y in range(height):
        if y < horizon:
            t = y / horizon
            colour = (int(150 + 80 * t), int(190 + 50 * t), int(230 + 20 * t))
        else:
            t = (y - horizon) / (height - horizon)
            colour = (int(40 + 30 * t), int(90 + 20 * t), int(120 + 10 * t))
        draw.line([(0, y), (width, y)], fill=colour)
    draw.polygon(
        [(0, horizon), (width * 0.3, horizon - 260), (width * 0.55, horizon)],
        fill=(62, 88, 70),
    )
    draw.ellipse([width * 0.72, 180, width * 0.72 + 180, 360], fill=(255, 240, 200))
    grain = rng.normal(0, 3, (height, width, 3))
    pixels = np.clip(np.asarray(image, dtype=np.float64) + grain, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels).filter(ImageFilter.GaussianBlur(1.2))


def _heading(pdf: canvas.Canvas, text: str, y: float) -> None:
    pdf.setFillColor(SLATE)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(72, y, text)


def _body(pdf: canvas.Canvas, top: float, lines: int) -> None:
    pdf.setFillColor(HexColor("#5B6674"))
    pdf.setFont("Helvetica", 10.5)
    words = (PARAGRAPH + " ") * 12
    y, start = top, 0
    for _ in range(lines):
        pdf.drawString(72, y, words[start : start + 92])
        start += 92
        y -= 15


def build_sample(path: Path) -> None:
    width, height = LETTER
    pdf = canvas.Canvas(str(path), pagesize=LETTER)
    pdf.setTitle("Harbour Line ferry terminal: design proposal")

    # 1. Cover
    pdf.setFillColor(SLATE)
    pdf.rect(0, height - 330, width, 330, stroke=0, fill=1)
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawString(72, height - 200, "Harbour Line")
    pdf.drawString(72, height - 238, "Ferry Terminal")
    pdf.setFont("Helvetica", 13)
    pdf.drawString(72, height - 275, "Design proposal · draft for review")
    pdf.setFillColor(BLUE)
    pdf.rect(72, 120, 140, 6, stroke=0, fill=1)
    pdf.showPage()

    # 2. Contents
    _heading(pdf, "Contents", height - 110)
    pdf.setFont("Helvetica", 12)
    for i, item in enumerate(
        ["Site today", "The new hall", "Passenger flow", "Budget", "Views", "Schedule"]
    ):
        pdf.setFillColor(SLATE)
        pdf.drawString(72, height - 160 - i * 28, f"{i + 1}.  {item}")
        pdf.setFillColor(BLUE)
        pdf.drawRightString(width - 72, height - 160 - i * 28, str(i + 3))
    pdf.showPage()

    # 3-4. Text
    for title in ("Site today", "The new hall"):
        _heading(pdf, title, height - 110)
        _body(pdf, height - 145, 28)
        pdf.setFillColor(MIST)
        pdf.rect(72, 110, width - 144, 150, stroke=0, fill=1)
        pdf.showPage()

    # 5. Chart
    _heading(pdf, "Passenger flow", height - 110)
    values = [62, 88, 74, 120, 140, 118, 96]
    for i, value in enumerate(values):
        pdf.setFillColor(BLUE if i != 4 else SLATE)
        pdf.rect(90 + i * 62, 200, 40, value * 2.6, stroke=0, fill=1)
    _body(pdf, 170, 5)
    pdf.showPage()

    # 6. Photo
    _heading(pdf, "Views", height - 110)
    pdf.drawImage(ImageReader(_photo(1)), 72, height - 480, width - 144, 340)
    _body(pdf, height - 510, 12)
    pdf.showPage()

    # 7. Table
    _heading(pdf, "Budget", height - 110)
    rows = [("Hall", "4.2"), ("Berth works", "2.9"), ("Cycle parking", "0.4"), ("Total", "7.5")]
    for i, (label, amount) in enumerate(rows):
        y = height - 170 - i * 34
        pdf.setFillColor(MIST if i % 2 == 0 else HexColor("#FFFFFF"))
        pdf.rect(72, y - 10, width - 144, 34, stroke=0, fill=1)
        pdf.setFillColor(SLATE)
        pdf.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 12)
        pdf.drawString(84, y + 2, label)
        pdf.drawRightString(width - 84, y + 2, f"${amount}M")
    pdf.showPage()

    # 8. Photo, full page
    pdf.drawImage(ImageReader(_photo(2, width=2550, height=3300)), 0, 0, width, height)
    pdf.showPage()

    pdf.save()


def _pump(seconds: float) -> None:
    from PySide6.QtCore import QCoreApplication, QEventLoop

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def _save(window: object, name: str) -> None:
    from PySide6.QtWidgets import QWidget

    assert isinstance(window, QWidget)
    buffer = io.BytesIO()
    image = window.grab().toImage()
    image.save(str(OUT / name))
    # Re-save through Pillow with optimisation: the repo's pre-commit hook
    # refuses files over 512 KB.
    with Image.open(OUT / name) as png:
        png.convert("RGB").save(buffer, format="PNG", optimize=True)
    (OUT / name).write_bytes(buffer.getvalue())
    print(f"wrote docs/images/{name}  ({len(buffer.getvalue()) // 1024} KB)")


def main() -> int:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from modpdf import tasks
    from modpdf.gui import settings, theme
    from modpdf.gui.session import load
    from modpdf.gui.window import MainWindow

    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="modpdf-shots-"))
    sample = work / "ferry-terminal-proposal.pdf"
    build_sample(sample)

    # Never read or write the real per-user preferences from this script:
    # point the app's settings at a throwaway file with every default.
    scratch_settings = str(work / "settings.ini")
    settings.QSettings = lambda: QSettings(  # type: ignore[assignment,misc]
        scratch_settings, QSettings.Format.IniFormat
    )

    app = QApplication.instance() or QApplication(sys.argv)

    # Light: the page grid with two pages selected.
    theme.set_mode(dark=False)
    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    window._loaded(load(sample))
    _pump(4)
    window.grid.item(2).setSelected(True)
    window.grid.item(3).setSelected(True)
    _pump(0.5)
    _save(window, "app-light.png")
    window.close()

    # Dark: the Compress panel after a real compression of the same file.
    theme.set_mode(dark=True)
    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    window._loaded(load(sample))
    window._show_panel("compress")
    _pump(4)
    result = tasks.compress_file(
        sample, work / "smaller.pdf", mode="visual", level="balanced", overwrite=True
    )
    window._compressed(result, "balanced")
    _pump(0.5)
    _save(window, "app-dark-compress.png")
    window.close()

    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
