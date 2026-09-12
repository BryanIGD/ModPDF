"""Tests for the no-network guarantee.

This is the project's central claim, so it is tested from both directions: that
network calls genuinely fail, and that real PDF work genuinely succeeds while
they are failing. A guard that blocked the network by breaking the program
would pass the first half and be useless.
"""

from __future__ import annotations

import socket
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from modpdf.cli import app, main
from modpdf.security import netguard
from modpdf.security.netguard import NetworkBlockedError
from tests.conftest import PageMaker, page_markers

runner = CliRunner()


@pytest.fixture
def guarded() -> Iterator[None]:
    """Install the guard for one test and always take it back off again."""
    netguard.install()
    try:
        yield
    finally:
        netguard.uninstall()


@pytest.mark.usefixtures("guarded")
class TestTheNetworkIsUnreachable:
    def test_a_plain_socket_is_refused(self) -> None:
        with pytest.raises(NetworkBlockedError):
            socket.socket()

    def test_ipv6_is_refused(self) -> None:
        with pytest.raises(NetworkBlockedError):
            socket.socket(socket.AF_INET6, socket.SOCK_STREAM)

    def test_family_as_a_keyword_is_refused(self) -> None:
        """The obvious way to slip past a guard that only checks positionals."""
        with pytest.raises(NetworkBlockedError):
            socket.socket(family=socket.AF_INET)

    def test_create_connection_is_refused(self) -> None:
        with pytest.raises(NetworkBlockedError):
            socket.create_connection(("example.com", 80))

    def test_name_resolution_is_refused(self) -> None:
        """A DNS lookup is itself an outbound message, so it leaks even if it fails."""
        with pytest.raises(NetworkBlockedError):
            socket.getaddrinfo("example.com", 80)
        with pytest.raises(NetworkBlockedError):
            socket.gethostbyname("example.com")

    def test_tls_wrapping_is_refused(self) -> None:
        with pytest.raises(NetworkBlockedError):
            ssl.create_default_context().wrap_socket(object())  # type: ignore[arg-type]

    def test_an_http_request_cannot_get_out(self) -> None:
        """The path a telemetry call in a dependency would actually take."""
        with pytest.raises((NetworkBlockedError, urllib.error.URLError, OSError)):
            urllib.request.urlopen("http://example.com", timeout=2)

    @pytest.mark.skipif(sys.platform == "win32", reason="no Unix sockets")
    def test_unix_sockets_still_work(self) -> None:
        """They cannot reach a network, and breaking local IPC buys nothing."""
        # Windows has no socket.AF_UNIX, in the stubs or at run time; the inner
        # check is what mypy needs when it checks the suite for that platform.
        if sys.platform != "win32":
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.close()


class TestTheGuardIsWellBehaved:
    def test_install_is_idempotent(self) -> None:
        netguard.install()
        netguard.install()
        try:
            assert netguard.is_installed()
        finally:
            netguard.uninstall()
        assert not netguard.is_installed()

    def test_uninstall_restores_real_sockets(self) -> None:
        netguard.install()
        netguard.uninstall()
        sock = socket.socket()
        sock.close()

    def test_uninstall_without_install_is_harmless(self) -> None:
        netguard.uninstall()
        assert not netguard.is_installed()

    def test_the_context_manager_leaves_no_trace(self) -> None:
        with netguard.denied():
            assert netguard.is_installed()
        assert not netguard.is_installed()


class TestTheCliTurnsItOn:
    def test_the_entry_point_installs_the_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The claim is only worth anything if the real entry point does this."""
        monkeypatch.setattr(sys, "argv", ["modpdf", "--version"])
        try:
            with pytest.raises(SystemExit):
                main()
            assert netguard.is_installed(), "modpdf ran without blocking the network"
        finally:
            netguard.uninstall()


class TestRealWorkStillWorks:
    """A guard that blocked the network by breaking the program would be useless."""

    def test_split_works_with_the_network_blocked(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        source = make_pdf(9, name="doc.pdf")
        with netguard.denied():
            result = runner.invoke(
                app, ["split", str(source), "--every", "3", "-o", str(tmp_path / "out")]
            )
        assert result.exit_code == 0
        pieces = sorted((tmp_path / "out").iterdir())
        assert [page_markers(p) for p in pieces] == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]

    def test_merge_works_with_the_network_blocked(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        first = make_pdf(2, name="a.pdf")
        second = make_pdf(3, name="b.pdf")
        out = tmp_path / "merged.pdf"
        with netguard.denied():
            result = runner.invoke(app, ["merge", str(first), str(second), "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [1, 2, 1, 2, 3]

    def test_reorder_works_with_the_network_blocked(
        self, make_pdf: PageMaker, tmp_path: Path
    ) -> None:
        source = make_pdf(4)
        out = tmp_path / "out.pdf"
        with netguard.denied():
            result = runner.invoke(app, ["reorder", str(source), "--order", "4,1", "-o", str(out)])
        assert result.exit_code == 0
        assert page_markers(out) == [4, 1]
