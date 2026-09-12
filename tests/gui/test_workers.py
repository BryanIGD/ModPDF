"""Tests for `modpdf.gui.workers`: routing work off the UI thread.

Every other GUI test bypasses `workers.run` and calls the underlying task
function directly, treating the threading as "already covered elsewhere" —
this is elsewhere. These tests let a real `QThreadPool` job run to
completion and poll the real Qt event loop for delivery, because the bug
this module exists to prevent (see its own docstring) is specifically about
that delivery: a job whose Python reference is dropped before its
cross-thread signal reaches the main thread can vanish without a trace, no
exception and no callback — which is exactly what made opening a second file
onto an existing workspace hang forever on "Adding…" until it was found here.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from modpdf.gui import workers

pytestmark = pytest.mark.usefixtures("qt_app")


def pump(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Process the real Qt event loop until `condition()` is true, or give up."""
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def fail(exc: Any) -> None:
    pytest.fail(f"unexpected: {exc}")


class TestASingleJob:
    def test_the_result_reaches_on_done(self) -> None:
        results: list[object] = []
        workers.run(lambda: 42, on_done=results.append, on_failed=fail)
        assert pump(lambda: bool(results)), "on_done was never called"
        assert results == [42]

    def test_an_expected_error_reaches_on_failed_not_on_crashed(self) -> None:
        def boom() -> None:
            raise ValueError("nope")

        failures: list[Exception] = []
        workers.run(
            boom,
            on_done=lambda _r: pytest.fail("should not have succeeded"),
            on_failed=failures.append,
            on_crashed=lambda trace: pytest.fail(f"should have been expected: {trace}"),
        )
        assert pump(lambda: bool(failures)), "on_failed was never called"
        assert isinstance(failures[0], ValueError)

    def test_an_unexpected_error_reaches_on_crashed(self) -> None:
        def boom() -> None:
            raise RuntimeError("a real bug")

        crashes: list[str] = []
        workers.run(
            boom,
            on_done=lambda _r: pytest.fail("should not have succeeded"),
            on_failed=fail,
            on_crashed=crashes.append,
        )
        assert pump(lambda: bool(crashes)), "on_crashed was never called"
        assert "RuntimeError" in crashes[0]


class TestAJobStartedFromAnothersOnDone:
    """The exact shape that exposed the bug: a second job started from
    inside the first job's own `on_done`, with nothing else in the caller
    keeping either job alive — precisely what opening a second file onto an
    existing workspace looks like, since that appends its pages as one job
    and then opens the combined file that job just wrote as a second one."""

    def test_the_chained_job_still_completes(self) -> None:
        results: list[object] = []

        def start_second(first_result: object) -> None:
            results.append(first_result)
            workers.run(lambda: "second", on_done=results.append, on_failed=fail)

        workers.run(lambda: "first", on_done=start_second, on_failed=fail)

        assert pump(lambda: len(results) == 2), f"chained job never completed: {results}"
        assert results == ["first", "second"]

    def test_a_longer_chain_completes(self) -> None:
        """More than one hop, so a fix that happens to survive exactly two
        chained jobs but not more would still be caught."""
        results: list[int] = []

        def on_done(remaining: int) -> Callable[[object], None]:
            def handler(_result: object) -> None:
                results.append(remaining)
                if remaining > 0:
                    workers.run(lambda: None, on_done=on_done(remaining - 1), on_failed=fail)

            return handler

        workers.run(lambda: None, on_done=on_done(4), on_failed=fail)

        assert pump(lambda: len(results) == 5), f"chain stalled after: {results}"
        assert results == [4, 3, 2, 1, 0]


class TestAJobIsReleasedOnceDelivered:
    """`_INFLIGHT` is what keeps a job alive until its signal is delivered —
    see the module docstring. It should not go on holding jobs forever."""

    def test_inflight_is_empty_again_once_the_job_completes(self) -> None:
        done: list[object] = []
        workers.run(lambda: None, on_done=done.append, on_failed=fail)
        assert pump(lambda: bool(done)), "job never completed"
        assert workers._INFLIGHT == set()
