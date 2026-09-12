# Contributing

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
git clone https://github.com/BryanIGD/ModPDF.git
cd ModPDF
uv sync --all-groups
uv run pytest
```

Before opening a pull request, all of these should pass — they're exactly
what CI runs:

```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -v --cov
```

## YAGNI is enforced, not aspirational

This is a security-focused tool, and bloat in a security tool is worse than
bloat elsewhere: every abstraction is more code someone has to read before
they can trust it. Concretely:

- **Build only what a shipped command needs.** No feature flags, config
  options, or extension points without a caller today.
- **No abstraction before a second implementation exists.** We call pikepdf
  directly; there is no `PdfEngine` interface, because there is no second
  engine. If one ever appears, extract the interface then, informed by real
  requirements instead of a guess.
- **Every dependency must be load-bearing.** Adding one means updating the
  comment in `pyproject.toml` that names the count, adding an inline comment
  saying what it's for, and — if it changes the shape of a real decision, not
  just a version bump — a note in `docs/adr/`.
- **Flat over deep.** One module per concept. Split a file when it's
  genuinely hard to read, not in anticipation of it becoming so.

If a change adds a layer "for future flexibility," it needs a real, current
caller in the same pull request, or the flexibility waits until something
actually needs it.

## How this project writes documentation

The README and this file are written the way a person explains something to
another person, not the way software project marketing usually reads. In
practice:

- No emoji in headings, no "blazing fast," no badge walls.
- Examples show real output from the actual commands, not invented sample
  text — the point of `tests/conftest.py`'s generated fixtures is that
  examples can be captured and stay true.
- A limitations section should be specific and slightly unflattering. "This
  won't shrink a text-only PDF much, here's why" is worth more than silence
  on the subject.
- If a sentence could be deleted without losing information, delete it.

## Tests

Every PDF the test suite touches is generated at test time by
`tests/conftest.py`; no real document is ever committed, and pages carry a
marker so a test can assert that page 3 really is the page that started as
page 3 after a split or reorder — not just that the page *count* looks right.

- An operation change needs a test asserting page **identity**, not only page
  count.
- A change to anything in `modpdf/security/` needs a test in
  `tests/security/`, and if it touches the network guard specifically,
  confirm the change still passes with the network blocked.
- A GUI change that reaches `modpdf.tasks` needs the window-level test to
  call the task function directly (as the existing GUI tests do) rather than
  only exercising it through a live `QThreadPool` job — except when the
  threading itself is what's being tested, as in `tests/gui/test_workers.py`.

## Structure

The command line and the desktop app are two interfaces over one set of
functions in `modpdf/tasks.py`. Neither implements a PDF operation of its
own, and neither can reach the filesystem without going through
`modpdf/security/`. A change that adds behavior only one interface can use is
a sign it belongs in the wrong layer.

## Commit messages and pull requests

Say what changed and why, the way the rest of this codebase's comments do.
"Fix bug" is not that; "the page-count check ran before the password prompt,
so an encrypted file always failed" is.
