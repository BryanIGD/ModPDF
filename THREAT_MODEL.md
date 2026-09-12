# Threat model

This is the specific version of the README's privacy claim: what ModPDF
defends against, how, and — the part that matters more — what it explicitly
does not defend against. A security document that only lists what a program
protects against is marketing. The list below is the other one.

## What "local-only" actually means

ModPDF removes its own ability to open a network socket at process startup,
before a document is read or a window is shown. This is not a setting that
can be left on by mistake: `socket.socket`, `socket.create_connection` and
the `ssl` module's connection entry points are replaced with functions that
raise. `tests/security/test_no_network.py` asserts this directly, and CI runs
the entire suite a second time inside a network namespace with no interfaces
at all, so the guarantee is checked by two independent mechanisms rather than
one that could be quietly disabled.

What this buys you: a PDF this tool opens cannot phone home, and neither can
a compromised or careless dependency, because the process has no working
sockets to use even if it tried. What it does not buy you: see below.

## What we defend against

- **Exfiltration over the network** — the guard above. Verified by tests, not
  asserted in prose.
- **Malformed and hostile PDFs** — parsing is delegated entirely to QPDF and
  PDFium, both hardened against two decades of real-world malformed input, so
  this project never parses PDF structure itself. File-size and page-count
  limits refuse decompression-bomb-shaped input before it is processed.
  JavaScript and XFA content are read and reported by `inspect`, never
  executed or rendered.
- **Accidental disclosure through a sync folder** — writing into an iCloud
  Drive, Dropbox, Google Drive or OneDrive folder is detected and warned
  about, because "nothing leaves your computer" is false the moment the
  output lands somewhere that uploads it automatically.
- **Passwords ending up somewhere they shouldn't** — never accepted as a
  command-line argument (visible to any process via `ps`, and kept in shell
  history); only `--password-stdin` or an environment variable.
- **Partial or corrupted output** — every write is staged next to its
  destination and moved into place with an atomic rename, so a crash or kill
  mid-write leaves either the old file or nothing, never a truncated one that
  looks plausible.
- **Content that looks deleted but isn't** — `inspect` surfaces earlier
  revisions still recoverable inside a file (a common result of editors that
  append changes instead of rewriting), and `sanitize` rebuilds a document
  from its pages rather than deleting references, so stripped content is
  actually absent from the output rather than merely unlinked.
- **A dependency silently changing underneath a release** — the lockfile is
  committed and hash-verified in CI, `pip-audit` runs against it on every
  pull request and weekly on a schedule, and `bandit` checks this project's
  own code for the common ways security bugs get introduced by accident.

## What we do not defend against

- **A compromised operating system.** If something already has code execution
  on the machine ModPDF runs on — a keylogger, a malicious kernel module, a
  RAT — nothing here helps. ModPDF's guarantees are about what *this process*
  does, not about the integrity of the system underneath it.
- **A person with access to the machine.** Physical or account access to the
  computer is not something a desktop application can defend against.
- **Backup and indexing systems copying scratch state.** Time Machine,
  Spotlight, or an antivirus scanner reading temporary files while they exist
  on disk is outside this project's control. Temp files are created privately
  (mode 0600, in the destination's own directory) and removed after use, but
  "removed" is best-effort on an SSD or a copy-on-write filesystem like APFS,
  not a forensic guarantee — this project does not claim otherwise.
- **The user sharing the output themselves.** If you compress a file and then
  email, upload, or Slack it to someone, that is a disclosure you chose to
  make. ModPDF's job ends at "nothing left this computer on its own."
- **Process isolation.** ModPDF runs in a single process with no sandboxing
  and no subprocess isolation. This is deliberate rather than an oversight —
  see "Not built yet" in the README — but it means a bug that defeats QPDF's
  or PDFium's own hardening runs with this process's full privileges, not a
  restricted worker's.
- **A dependency compromised before it reaches the lockfile.** `pip-audit`
  catches known CVEs in what's already pinned; it cannot catch a malicious
  release published *before* anyone knew to flag it. Hash-pinning and a
  committed lockfile narrow this window; nothing removes it.
- **Redaction.** Not a threat this tool takes on at all yet. See "What it
  will not do" in the README for why drawing a black box over text is not
  redaction and won't be shipped until it can be done correctly.

## If you find a gap in this list

That's a real finding — see [SECURITY.md](SECURITY.md).
