"""Getting a document password from the user without leaking it.

There is deliberately no ``--password`` option that takes the password as its
value. Command-line arguments are not private: on Linux and macOS any user on
the machine can read another process's arguments straight out of ``ps``, and the
password also lands in the shell history file, where it stays. A flag like that
would hand over the key to an encrypted document to anyone with a shell account
and the patience to run ``ps`` in a loop.

So a password arrives one of three ways, in this order of preference:

* ``--password-stdin``, which is what scripts and pipelines should use
* the ``MODPDF_PASSWORD`` environment variable, for CI and automation
* an interactive prompt with no echo, for a person at a terminal

None of the three is perfect. An environment variable is visible to child
processes and appears in ``/proc/<pid>/environ`` on Linux, so it is offered for
convenience rather than recommended. Standard input is the one to use when it
matters.

A note on erasing it afterwards: Python strings are immutable and garbage
collected, so a password cannot be reliably wiped from memory once read. Saying
otherwise would be theatre. What we do instead is never write it anywhere — not
to a log, not to a temporary file, not into an error message.
"""

from __future__ import annotations

import getpass
import os
import sys

__all__ = ["ENVIRONMENT_VARIABLE", "ask", "resolve"]

ENVIRONMENT_VARIABLE = "MODPDF_PASSWORD"


def resolve(*, use_stdin: bool = False) -> str | None:
    """Get a password without prompting. Returns None if none was supplied.

    Args:
        use_stdin: Read one line from standard input. Set by --password-stdin.
    """
    if use_stdin:
        line = sys.stdin.readline()
        if not line:
            return None
        # Only the trailing newline is stripped. A password may legitimately
        # begin or end with a space, and quietly trimming it would produce a
        # "wrong password" that the user cannot explain.
        return line.rstrip("\n").rstrip("\r")

    from_environment = os.environ.get(ENVIRONMENT_VARIABLE)
    if from_environment:
        return from_environment

    return None


def ask(filename: str) -> str | None:
    """Prompt for a password with no echo. Returns None if there is no terminal.

    Called only after an open has already failed for want of a password, so the
    prompt appears when it is actually needed rather than on every run.
    """
    if not sys.stdin.isatty():
        return None
    try:
        return getpass.getpass(f"Password for {filename}: ")
    except (EOFError, KeyboardInterrupt):
        return None
