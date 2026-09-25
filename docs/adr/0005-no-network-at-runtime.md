# ADR-0005: Remove network access at runtime instead of promising it

Status: accepted (2026-09-11)

## Context

ModPDF's main promise is that documents never leave the computer. Every tool
that quietly uploads files makes the same promise in its README. ModPDF
contains no networking code, but that's a claim about code most users will
never read, and it can stop being true without anyone noticing: a dependency
adds telemetry, or a later contributor adds an update check.

## Decision

The first thing both entry points do, before parsing arguments or opening a
file, is call `modpdf.security.netguard.install()`. It replaces Python's
socket constructor, `socket.create_connection`, DNS lookups
(`getaddrinfo`, `gethostbyname`) and TLS wrapping with functions that raise
`NetworkBlockedError`. There is no flag to turn it off. Unix domain sockets
are allowed, because they can't reach a network.

It's checked two ways:

- `tests/security/test_no_network.py` asserts that sockets, DNS and HTTP
  calls all fail while the guard is on, and that real PDF work still
  succeeds.
- CI runs the whole test suite a second time with
  `unshare --net`, inside a network namespace with no interfaces at all.

## Why

A capability that has been removed is worth more than a promise. A network
call can't happen by accident, through a dependency, or through a future
change by someone who forgot. And the claim is checkable: anyone can read
`netguard.py` in a couple of minutes and run the tests.

The DNS functions are blocked too, because a DNS lookup is itself an outbound
message. A leak doesn't need the connection to succeed.

## What we gave up

- No update checks, crash reports or usage statistics, ever. Updates happen
  through whatever installed ModPDF.
- It only covers Python. Native code calling the operating system's socket
  functions directly would get past the patches. That's why the CI job exists:
  a namespace with no interfaces stops native code too.
- It isn't protection against malware. Anything running as the same user can
  undo the patches. It defends against mistakes, ours and our dependencies',
  which is the realistic risk. THREAT_MODEL.md says this plainly.
