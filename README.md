# ModPDF

Split, merge, reorder and compress PDFs on your own machine. Your documents are
never uploaded anywhere, because there is no code in this program that could
upload them.

The intended end state is stronger than that: the process will block its own
ability to open a socket at all, so the claim can be tested rather than taken
on trust. That guard is specified and is the next thing being built — see
Status below, which is kept accurate about what actually runs today.

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

Early development, and honest about it: the build plan has seven phases and
this is the end of Phase 1. Three commands work. Compression, which is the
interesting one, does not exist yet.

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
shows you the plan before anything is written:

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

Mistakes are refused rather than guessed at:

```
$ modpdf reorder report.pdf --order 99 -o bad.pdf
error: '99' refers to page 99, but the document has 23 pages
```

Along the way, some things that are easy to get wrong and that ModPDF gets
right:

- **Bookmarks survive.** Splitting a report rebuilds each piece's outline
  against its new page numbers. Entries whose page ended up in a different
  piece are dropped; entries whose *parent* heading was dropped are promoted
  rather than deleted along with it, so you do not lose a chapter's worth of
  navigation over one missing heading.
- **Metadata survives**, because reordering two pages should not silently erase
  a document's title. Stripping metadata will be an explicit choice, which is
  what `sanitize` is for.
- **Nothing is half-written.** Output is staged beside its destination and
  moved into place atomically. Interrupt it and you have either the old file or
  no file, never a truncated PDF that opens far enough to look fine.
- **Output is private.** Files are created mode `0600` and split directories
  `0700`, so pieces of a confidential document are not left readable by other
  accounts on the machine.
- **Existing files are never overwritten** unless you pass `--force`.

## Not built yet

`compress`, `inspect` and `sanitize`. The enforced no-network guard is
specified and tested for in the plan but not yet implemented — so for now, the
"it cannot phone home" claim rests on there being no network code, which is
weaker than what is intended and worth saying plainly.

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

## Licence

Apache 2.0. See LICENSE, and NOTICE for the third-party components ModPDF
depends on.
