# ADR-0004: Check every compressed page before keeping the result

Status: accepted (2026-09-11)

## Context

Compression that actually shrinks a file is lossy: it downsamples and
re-encodes images. We wanted that on by default, because a lossless-only tool
barely shrinks anything. But a user compressing a 200-page contract isn't
going to look at every page afterwards, and one ruined page could go
unnoticed until it matters.

## Decision

`modpdf/verify.py` checks every compressed file against the original before
`compress` keeps it:

1. **Structure.** The page count is the same and the file reopens cleanly.
2. **Text.** Every page's extracted text is identical once whitespace is
   normalised.
3. **Pixels.** Every page is rendered at 150 DPI, before and after, and
   compared. It fails if more than 5% of a page's pixels changed visibly, or
   if any single region changed almost completely.

If any page fails, the whole document falls back to the lossless result, and
the report says why. If the result isn't smaller than the original, the
original is kept and the report says it was already optimal.

## Why

It turns "compresses without visible loss" from a promise into something the
program checks every time. The worst case becomes a file that didn't shrink
as much as hoped, never one that looks worse.

The pixel check measures how much of the page changed, not the single worst
pixel. A first version used the worst pixel and failed on ordinary scans of
text: resampling moves a letter's edge by a fraction of a pixel, which flips
a few edge pixels from white to black on a page that looks identical. The
fraction of changed pixels tells that apart from real damage.

## What we gave up

- **Speed.** Every page is rendered twice, which makes compression slower on
  large documents.
- **Partial results.** One bad page sends the whole document back to
  lossless, even if every other page compressed well. Falling back page by
  page would keep the good pages. It hasn't been built.
- **A perceptual metric.** A fraction of changed pixels isn't SSIM. It has
  been good enough so far. If it ever passes something that looks visibly
  worse, that's the case for moving to SSIM.
- **A dependency.** Measuring that fraction quickly pulled in numpy.

## Consequences

- pypdfium2 is required for compression, not just for the desktop app's
  thumbnails (see ADR-0002).
- New compression ideas get tested against the gate before they ship. That's
  how the CMYK inversion was found: the gate failed a cyan swatch that had
  turned white.
- `--level high` is the one setting allowed to accept a more visible
  difference, and it does that by widening the gate's limits for that level,
  not by skipping the check.
