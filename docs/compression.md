# How compression works

This is the long version of the README's compression section. The short
version: a text-only PDF won't get much smaller, the big savings come from
images, and every compressed file is checked against the original before it's
kept.

A PDF that is text and vector graphics is already a set of compressed drawing
commands — there is no clever trick left to apply. Every dramatic size
reduction you've seen advertised came from one thing: recompressing scanned
images. `compress` is honest about that rather than pretending otherwise:

```
$ modpdf compress deposition.pdf -o smaller.pdf
smaller.pdf  55.1 KB → 6.0 KB  (89% smaller)
  images     1 recompressed, 0 left alone   45.3 KB → 4.7 KB
  quality    text identical · largest visible difference 2.0% of one page   PASS
```

Every page is rendered and compared against the original before the result is
accepted. If any page looks different enough to matter, the whole document
falls back to a lossless result instead and says so — the worst case is a file
smaller than you hoped for, never one that looks worse.

`--level` picks how hard to push that trade-off, rather than leaving you to
guess at a DPI number: `low` barely touches anything, and `balanced` (the
default) is a sensible middle ground.

`high` ("Maximum compression" in the desktop app) is tuned for a different
job than the other two, and it is worth being direct about what it actually
buys you. Its own image resolution and JPEG quality are deliberately kept
close to lossless — raised on purpose after an early, more aggressive version
made a flattened diagram's own small text hard to read — so on a document
like the scan above, whose only large content is one image, `high` has
little left to trade and lands close to `balanced`:

```
$ modpdf compress deposition.pdf -o smaller.pdf --level high
smaller.pdf  55.1 KB → 6.0 KB  (89% smaller)
  images     1 recompressed, 0 left alone   45.3 KB → 4.8 KB
  quality    text identical · largest visible difference 1.9% of one page   PASS
  note       maximum compression: image quality was reduced on purpose to shrink the file further
```

Where `high` earns its name is a document whose bulk is not an image at all.
Not every large PDF is large because of its images: a complex vector diagram
— thousands of curves and fills a design tool exported directly as drawing
commands, not as a picture — can outweigh every image in the file combined,
and no image setting touches it, because it is not an image. Both `balanced`
and `high` rasterize a page whose own vector content is heavy enough to be
worth it, each at its own resolution and JPEG quality, while leaving every
character of text on that page exactly as it was — including text that is
itself part of the diagram, like a box's own label. `low` never does this; it
promises to barely touch anything, and a rasterized page is a bigger change
than that:

```
$ modpdf compress paper.pdf -o smaller.pdf --level balanced
paper.pdf  2.3 MB → 1.7 MB  (26% smaller)
  images     3 already at or below the target, left alone
  vector     1 page of complex vector art flattened to an image
  quality    text identical · largest visible difference 0.1% of one page   PASS

$ modpdf compress paper.pdf -o smaller.pdf --level high
paper.pdf  2.3 MB → 1.3 MB  (45% smaller)
  images     3 already at or below the target, left alone
  vector     1 page of complex vector art flattened to an image
  quality    text identical · largest visible difference 0.5% of one page   PASS
  note       maximum compression: image quality was reduced on purpose to
             shrink the file further; text stays selectable even on a
             flattened page — only its vector art was
```

So `high` is not a blanket "always the smallest file" promise — it is a
promise about what happens when there is vector content worth flattening.
On a document without any, `balanced` can legitimately win, as the scan
example above shows.

`balanced`'s flattened result is still held to the same strict, unwidened
quality gate as the rest of what it does — the same gate that would fall the
whole document back to lossless if a flattened page ever looked wrong — so
turning this on for `balanced` did not loosen its "no visible loss" promise;
only `high` does that.

`--lossless` skips images entirely and only does the safe structural cleanup —
not one pixel or glyph changes, and `--level` has nothing to do in this mode:

```
$ modpdf compress deposition.pdf -o smaller.pdf --lossless
smaller.pdf  55.1 KB → 46.5 KB  (16% smaller)
```

A text-only document will not shrink much either way — there is no image data
to recompress — and `compress` says so rather than inventing savings:

```
$ modpdf compress report.pdf -o smaller.pdf
smaller.pdf was already optimal
```

Which codec an oversized image gets depends on what is actually in it, not on
how it happens to be stored: content that is overwhelmingly near-black or
near-white — scanned text, even when the file stores it as ordinary 8-bit
grayscale rather than true 1-bit, which is the common case — gets CCITT Group
4, lossless for that kind of content and usually the largest single win in the
file. Genuine photographs and textured scans get JPEG at a conservative
quality. Left deliberately untouched: **CMYK images** (a naive re-encode was
tested against this project's own quality gate and came back with a pure cyan
swatch rendering as white — the well-known Adobe CMYK-JPEG inversion problem,
so this is a tested decision, not an oversight), **indexed/palette images**,
and any image carrying a transparency mask, since resizing the mask correctly
in lockstep with its parent is a feature this project intends to support but
does not yet.
