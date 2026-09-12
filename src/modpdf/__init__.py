"""ModPDF — split, merge, reorder and compress PDFs entirely on your own machine.

Nothing in this package opens a network connection. See `modpdf.security.netguard`
for the runtime enforcement of that promise, and THREAT_MODEL.md for what it does
and does not protect against.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("modpdf")
except PackageNotFoundError:  # source checkout without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
