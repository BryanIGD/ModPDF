# ModPDF

Split, merge, reorder and compress PDFs on your own machine. Your documents are
never uploaded anywhere, and the program goes further than promising that: at
startup it removes its own ability to open a network socket, so a network call
cannot happen by accident, through a dependency, or through a future version of
this program written by someone who forgot.

That is a claim you can check rather than trust. `tests/security/` asserts that
sockets, DNS lookups and HTTP requests all raise, that real PDF work still
succeeds while they are raising, and that the command-line entry point turns the
guard on. CI runs the whole suite a second time inside a network namespace with
no interfaces at all.

## Why this exists

Search for "split PDF" and every result in the first page is a website. You
upload your document to a server you know nothing about, it does the work, and
you download the result. For a restaurant menu that is fine. For a signed
contract, a medical record, a bank statement or anything covered by an NDA, you
have just disclosed the document to a third party, and most people doing it do
not realise that is what happened.

The desktop alternatives are not much better. Plenty of them bundle an updater
that phones home, or a crash reporter that uploads the document it crashed on.

ModPDF is the boring, local version. Your files stay where they are.

## Status

Early development. Four of seven phases are done: the three page operations,
the security layer they rest on, and compression with the verification harness
that makes it trustworthy.

There is no release to install. Everything below is real output from the
commands as they currently run.

## What works

```
$ modpdf split report.pdf --every 10 -o chapters/
23 pages → 3 files in chapters
  report-p001-010.pdf  10 pages
  report-p011-020.pdf  10 pages
  report-p021-023.pdf  3 pages
```

Each comma-separated group in `--pages` becomes its own file, and `--dry-run`
shows the plan before anything is written:

```
$ modpdf split report.pdf --pages 1-5,20- -o parts/ --dry-run
dry run — nothing written
23 pages → 2 files in parts
  report-p001-005.pdf  pages 1-5
  report-p020-023.pdf  pages 20-23
```

```
$ modpdf merge report.pdf appendix.pdf -o complete.pdf
2 files (23 + 4 pages) → complete.pdf 27 pages
```

`reorder` selects, rearranges and duplicates pages. The output contains exactly
the pages you list, in that order, so leaving a page out drops it — and it says
so rather than letting you find out later:

```
$ modpdf reorder report.pdf --order -1,1-3 -o summary.pdf
23 pages → summary.pdf 4 pages (19 pages dropped)
```

Page numbers work the way a print dialog works: they start at 1, ranges include
both ends, `12-` means "page 12 to the end", and `-1` is the last page.

### Finding out what is in a document

`inspect` answers the question worth asking before you forward a file: what is
in here besides the pages I can see? It reads and changes nothing.

```
$ modpdf inspect statement.pdf
statement.pdf
  3 pages · 3.1 KB · PDF 1.3 · not encrypted

  8 things worth knowing:

  JavaScript — 1 script entry
    PDF JavaScript can run when the file is opened. It is the most common
    way a PDF is used to attack the person reading it.
  Opens automatically — an /OpenAction is set
    Something is set to happen the moment the document is opened, without
    the reader choosing it.
  Launch action — 1 occurrence
    asks your PDF reader to run a program on your computer
  Embedded files — 1: payroll.xlsx
    Whole files are bundled inside this PDF and travel with it. They do not
    appear on any page.
  ...
```

It also reports **earlier revisions**, which is the one that catches out law
firms and governments: many editors save by appending changes rather than
rewriting the file, so previous drafts stay inside it and text that looks
deleted is still recoverable. `--json` gives the same information for scripts.

### Removing it

```
$ modpdf sanitize statement.pdf -o safe.pdf
safe.pdf 3 pages
  removed: JavaScript (1), automatic open action, Launch actions (1),
  embedded files (1), XFA form, metadata
  Pages and text are unchanged. This is not redaction:
  anything visible on a page is still there.
```

`sanitize` rebuilds the document from its pages rather than deleting references,
because unlinking a piece of JavaScript leaves it in the file and fully
recoverable. The payload bytes are absent from the output, and there is a test
that greps for them to prove it.

Plain web links are kept by default, since a citation in a report is content and
the reader has to click it. Actions that fire on their own or execute code are
not. `--strip-links` removes links too.

### Compressing it

A PDF that is text and vector graphics is already a set of compressed drawing
commands — there is no clever trick left to apply. Every dramatic size
reduction you've seen advertised came from one thing: recompressing scanned
images. `compress` is honest about that rather than pretending otherwise:

```
$ modpdf compress deposition.pdf -o smaller.pdf
smaller.pdf  461.4 KB → 13.5 KB  (97% smaller)
  images     1 recompressed, 0 left alone   387.1 KB → 12.2 KB
  quality    text identical · largest visible difference 2.8% of one page   PASS
```

Every page is rendered and compared against the original before the result is
accepted. If any page looks different enough to matter, the whole document
falls back to a lossless result instead and says so — the worst case is a file
smaller than you hoped for, never one that looks worse:

```
$ modpdf compress deposition.pdf -o smaller.pdf --target-dpi 15
smaller.pdf  461.4 KB → 388.3 KB  (16% smaller)
  images     1 recompressed, 0 left alone   387.1 KB → 442 B
  quality    fell back to lossless — page 1: a region differs almost
             completely (peak difference 250/255)
```

`--lossless` skips images entirely and only does the safe structural cleanup —
not one pixel or glyph changes:

```
$ modpdf compress deposition.pdf -o smaller.pdf --lossless
smaller.pdf  461.4 KB → 388.3 KB  (16% smaller)
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

### Things that are easy to get wrong, and are handled

- **Bookmarks survive.** Splitting a report rebuilds each piece's outline
  against its new page numbers. Entries whose parent heading ended up in a
  different piece are promoted rather than deleted with it, so you do not lose a
  chapter's worth of navigation over one missing heading.
- **Metadata survives** ordinary operations, because reordering two pages should
  not silently erase a document's title. Removing it is what `sanitize` is for.
- **Damage is reported.** QPDF quietly repairs a malformed PDF and usually does
  it well, but a recovered file can be missing content. ModPDF tells you:
  `warning: statement.pdf is damaged. It was repaired well enough to read, but
  content may be missing or altered (9 issues).`
- **Cloud folders are called out.** "Your documents never leave your computer"
  is false if the output lands in Dropbox. ModPDF resolves the destination and
  says so — it still writes the file, it just declines to let you believe
  something untrue.
- **Passwords never touch the command line.** There is no `--password VALUE`
  flag, because arguments are visible to every process on the machine through
  `ps` and land in your shell history. Use `--password-stdin` or
  `MODPDF_PASSWORD`.
- **Nothing is half-written.** Output is staged beside its destination and moved
  into place atomically, at mode `0600`, with split directories at `0700`.
  Interrupt it and you have either the old file or no file.
- **Hostile input fails safely.** Malformed, truncated, empty and
  wrong-type files are refused with a clear message and no partial output.

## The desktop app

There is a window as well as a terminal. It is an optional extra, so a command
line user never installs a GUI toolkit:

```
pip install modpdf[gui]
modpdf-gui                  # or: modpdf-gui statement.pdf
```

Open a document and you get its pages as thumbnails: select them, drag to
reorder, delete, duplicate, extract, split by range, compress. Nothing is
written until you save, because the window holds your edits as an ordering of
the original's pages rather than as a modified document — which is also why
Revert costs nothing.

**Open** builds a workspace out of more than one file, without a second
button for it: open `pdf1`, then choose `pdf2` through the same Open button
(or drop it onto the window), and the workspace holds `pdf1`'s pages followed
by `pdf2`'s — including any reordering or deletion already pending on `pdf1`,
because a second file arriving should not quietly undo the first one's
edits. Do it again and a third file joins the same way. Dropping several
files onto the window at once is a different, existing action — merge them
straight to a new file rather than into the workspace, which is what you
usually mean by dropping a whole batch in together. Combining files into a
workspace needs a real file on disk — pdfium and every whole-document
operation both require one — so each addition writes the combined result to
a private, `0700` scratch directory the window
creates for itself and deletes when it closes; it is never the user's chosen
output location, and nothing in it survives the session.

The two interfaces are not two implementations. Both call the same functions in
`modpdf/tasks.py`, so a fix reaches both, and the window cannot reach the
filesystem without going through the same security layer the terminal uses. It
blocks its own network access at startup exactly as the CLI does, and the test
suite asserts that a full open-edit-save cycle still works while the network is
blocked.

Two decisions carried over from the CLI's behaviour:

- **Thumbnails are never written to disk.** A thumbnail cache is a folder of
  readable pictures of confidential documents, sitting outside whatever
  protection the original had, and it would outlive the session that made it.
  Re-rendering on next launch is the cheaper trade.
- **There is no recent-files list**, for the same reason: a list of paths to
  confidential documents is itself a leak.

## Not built yet

Subprocess isolation and a wall-clock timeout, on purpose: a timeout that
cannot interrupt work already running inside a native library would silently
fail to fire, and shipping one would be worse than having none — so there is
none until the work runs in its own process.

Inside `compress` specifically: JBIG2 (a further improvement over CCITT G4 for
bilevel scans, needing an external encoder for a marginal gain), font
subsetting, and correct handling of transparency masks — see "Compressing it"
above for the images that are deliberately left untouched until that lands.

## What it will not do

Worth stating early, because these are deliberate and not on a roadmap.

**Redaction.** Drawing a black rectangle over text leaves the text in the file,
fully extractable, and this has leaked real documents from real institutions
more than once. We would rather ship nothing than ship the version of redaction
that is easy to build.

**Meaningful compression of text-only PDFs.** A PDF that is text and vector
graphics is already a set of compressed streams. There is no clever trick
waiting to be applied. Savings there come to roughly 5–25% and come from
structural cleanup, not magic. The dramatic numbers you see advertised
elsewhere — 90% and up — come from one thing only: recompressing scanned
images. When your document has scans in it, ModPDF will get those numbers too,
and it will tell you that is where they came from.

**Protecting you from your own computer.** If the machine is already
compromised, nothing here helps. See THREAT_MODEL.md, which is specific about
where the guarantees stop.

## Development

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```
git clone <this repo>
cd ModPDF
uv sync --all-groups
uv run pytest
```

Lint, types and tests all run in CI on macOS, Linux and Windows. `uv run ruff
check`, `uv run ruff format`, `uv run mypy`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions this codebase actually
enforces, and [THREAT_MODEL.md](THREAT_MODEL.md) for what the security claims
above do and do not cover. Found a security issue? See
[SECURITY.md](SECURITY.md) rather than opening a public issue.

## Licence

Apache 2.0. See LICENSE, and NOTICE for the third-party components ModPDF
depends on.
