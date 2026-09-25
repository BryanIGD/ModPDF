# Security policy

ModPDF processes documents people usually have a specific reason not to want
leaked, so a security bug here is not routine. Please report it privately
rather than as a public issue.

## Reporting a vulnerability

Use GitHub's private reporting for this repository: **Security → Report a
vulnerability**, or go directly to
<https://github.com/BryanIGD/ModPDF/security/advisories/new>. That opens a
draft advisory only the maintainers can see until it is resolved — nobody
else gets notified, and no public issue is created.

If that form is unavailable for any reason, open a regular issue asking for
another way to reach the maintainer rather than describing the vulnerability
in it.

Include what you'd include for any bug report: the version (or commit) you
tested, how to reproduce it, and what you expected instead. If it's a way to
defeat one of the specific guarantees this project makes — the network guard,
the atomic-write behaviour, a password ending up somewhere it shouldn't — say
which one; that's usually the fastest path to a fix.

## Scope

In scope: anything that lets a PDF this tool opens reach the network, execute
code, escape the output path it was given, or expose data (a password, a
page, a temp file) it shouldn't. Also in scope: a dependency substitution or
supply-chain issue that would ship in a release.

Out of scope, and not something a report needs to establish: a compromised
operating system, resident malware, or a person with existing access to the
machine ModPDF runs on. See [THREAT_MODEL.md](THREAT_MODEL.md) for where the
line actually is.

## Supported versions

Only the latest release gets security fixes. Check which version you have
with `modpdf --version`, and if you can, confirm the problem on the latest
release or on `main` before reporting.

## Process

There is no dedicated security team; this is maintained by one person. Expect
an acknowledgement within a few days, not an SLA. A confirmed vulnerability
gets a fix and a published advisory once one exists; credit is given unless
you ask otherwise.
