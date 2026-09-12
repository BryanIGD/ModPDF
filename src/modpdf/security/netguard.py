"""Stopping this process from reaching the network at all.

ModPDF contains no networking code. That is worth very little on its own: it is
a claim about code the user has not read, made by the people who wrote it, and
it is exactly the claim every tool that quietly uploads your documents also
makes. Dependencies change, a transitive library adds a telemetry call, and the
claim silently stops being true without anyone noticing.

So instead of promising, we remove the capability. At startup the process
replaces its own socket constructors with ones that refuse, which means a
network call cannot happen by accident, through a dependency, or through a
future version of this program written by someone who forgot. The guard is not
a flag; there is no way to turn it off from the command line.

What this is not: protection against a hostile program. Anything running with
your privileges can undo these patches in three lines, and malware already on
the machine does not need our sockets anyway. This defends against mistakes —
ours and our dependencies' — which is the realistic threat. THREAT_MODEL.md is
explicit about the rest.

Unix domain sockets are left alone. They cannot reach a network, they are how
some local machinery talks to itself, and breaking them would buy nothing.
"""

from __future__ import annotations

import socket
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

__all__ = ["NetworkBlockedError", "denied", "install", "is_installed", "uninstall"]


class NetworkBlockedError(RuntimeError):
    """Something tried to reach the network. ModPDF does not do that."""


_MESSAGE = (
    "blocked an attempt to use the network. ModPDF works entirely offline, so "
    "this should be impossible — please report it as a bug"
)

# socket.socket's signature uses -1 to mean "the default", which is AF_INET.
# Treating it as anything else would leave the common case wide open.
_DEFAULT_FAMILY = -1
_ALLOWED_FAMILIES = frozenset(
    {getattr(socket, name) for name in ("AF_UNIX",) if hasattr(socket, name)}
)

_saved: dict[str, Any] = {}


def install() -> None:
    """Remove this process's ability to open a network connection.

    Idempotent, so calling it twice is harmless. Called once from the CLI entry
    point, before any argument is parsed or any file is opened.
    """
    if _saved:
        return

    _saved["socket_init"] = socket.socket.__init__
    _saved["create_connection"] = socket.create_connection
    _saved["getaddrinfo"] = socket.getaddrinfo
    _saved["gethostbyname"] = socket.gethostbyname
    _saved["wrap_socket"] = ssl.SSLContext.wrap_socket

    original_init = _saved["socket_init"]

    def guarded_init(
        self: socket.socket,
        family: int = _DEFAULT_FAMILY,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        requested = kwargs.get("family", family)
        if requested not in _ALLOWED_FAMILIES:
            raise NetworkBlockedError(_MESSAGE)
        original_init(self, family, *args, **kwargs)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkBlockedError(_MESSAGE)

    socket.socket.__init__ = guarded_init  # type: ignore[method-assign]
    socket.create_connection = refuse
    # Name resolution is blocked too. A DNS lookup is itself an outbound
    # message, so a leak does not need the connection to succeed.
    socket.getaddrinfo = refuse
    socket.gethostbyname = refuse
    ssl.SSLContext.wrap_socket = refuse  # type: ignore[method-assign]


def uninstall() -> None:
    """Put the real socket functions back. For tests; the CLI never calls this."""
    if not _saved:
        return

    socket.socket.__init__ = _saved["socket_init"]  # type: ignore[method-assign]
    socket.create_connection = _saved["create_connection"]
    socket.getaddrinfo = _saved["getaddrinfo"]
    socket.gethostbyname = _saved["gethostbyname"]
    ssl.SSLContext.wrap_socket = _saved["wrap_socket"]  # type: ignore[method-assign]
    _saved.clear()


def is_installed() -> bool:
    return bool(_saved)


@contextmanager
def denied() -> Iterator[None]:
    """Block the network for the duration of a block. For tests."""
    already = is_installed()
    install()
    try:
        yield
    finally:
        if not already:
            uninstall()
