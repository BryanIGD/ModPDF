"""Running PDF work off the user interface thread.

Opening a four-hundred-page scan, rendering a thumbnail and writing a
compressed file are all slow enough to freeze a window, and a frozen window is
how a user concludes a program has crashed and force-quits it mid-write. So
every call into `modpdf` from the GUI goes through here.

Errors are carried back rather than raised: the same exception types the CLI
treats as user errors become a message on the status bar, and anything else
keeps its traceback so a real bug is still reported as one.

A `Job` is not kept alive by anything once `run()` returns it to its caller —
every call site here discards the return value, and a chained job (one
started from inside another's `on_done`, as the desktop app does when
opening a second file onto an existing workspace: append its pages, then
open the combined file that job just wrote) discards it before that first
job's own signal has even been delivered. Once nothing holds a Python
reference to the job or its `signals` object, it becomes eligible for garbage
collection; if that happens between `self.signals.done.emit(...)` posting the
cross-thread call and the main thread actually processing it, the callback is
silently lost — the window sits on "Adding…" forever, with no error and
nothing to look at. `_INFLIGHT` exists solely to hold that reference until
the callback has run.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from modpdf.document import DocumentError
from modpdf.pagespec import PageSpecError
from modpdf.security.fs import FileSystemError
from modpdf.security.limits import LimitExceededError

__all__ = ["EXPECTED_ERRORS", "Job", "JobSignals", "run"]

# The same set the CLI reports as a one-line message rather than a traceback.
EXPECTED_ERRORS = (
    PageSpecError,
    DocumentError,
    FileSystemError,
    LimitExceededError,
    ValueError,
    IndexError,
)


class JobSignals(QObject):
    """Signals a job can emit. Separate because QRunnable is not a QObject."""

    done = Signal(object)
    # Carries the exception itself, not a message: the window needs to tell an
    # encrypted document (ask for a password and retry) from a damaged one.
    failed = Signal(object)
    crashed = Signal(str)


class Job(QRunnable):
    """One call into modpdf, run on a worker thread."""

    def __init__(self, work: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        # We manage this job's lifetime ourselves, through `_INFLIGHT` — see
        # the module docstring. Leaving Qt's default autoDelete in place would
        # let the thread pool destroy the underlying object the moment
        # `run()` returns, which can race the cross-thread delivery of the
        # signal that same call just emitted.
        self.setAutoDelete(False)
        self._work = work
        self._args = args
        self._kwargs = kwargs
        self.signals = JobSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._work(*self._args, **self._kwargs)
        except EXPECTED_ERRORS as exc:
            self.signals.failed.emit(exc)
        except Exception:
            # Not something the user did wrong. Keep the traceback so it can be
            # reported, and say so plainly rather than dressing it up.
            self.signals.crashed.emit(traceback.format_exc())
        else:
            self.signals.done.emit(result)


# Jobs currently running, or finished but not yet delivered to the caller.
# Only `run()` and `_release()` below touch this.
_INFLIGHT: set[Job] = set()


def run(
    work: Callable[..., Any],
    *args: Any,
    on_done: Callable[[Any], None],
    on_failed: Callable[[Exception], None],
    on_crashed: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Job:
    """Start `work` on the global thread pool and route its outcome back."""
    job = Job(work, *args, **kwargs)
    _INFLIGHT.add(job)

    def _release(_: object) -> None:
        _INFLIGHT.discard(job)

    # The caller's own callback is connected first, so it always runs before
    # the job is released — the order two connections to the same signal fire
    # in is the order they were connected in.
    job.signals.done.connect(on_done)
    job.signals.done.connect(_release)
    job.signals.failed.connect(on_failed)
    job.signals.failed.connect(_release)
    if on_crashed is not None:
        job.signals.crashed.connect(on_crashed)
    job.signals.crashed.connect(_release)

    QThreadPool.globalInstance().start(job)
    return job
