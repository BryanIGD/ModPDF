"""Properties that must hold for any document and any page selection.

Example-based tests check the cases we thought of. These check the cases we did
not. Page operations have clean algebraic properties, so they are unusually well
suited to this: splitting and rejoining a document must give the pages back in
the order they started, and permuting pages then undoing the permutation must
return the original. Anything that violates either is a bug regardless of which
page counts we happened to write tests for.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pikepdf
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from modpdf.document import save_pdf
from modpdf.ops.merge import merge_documents
from modpdf.ops.select import select_pages
from tests.conftest import build_pdf, page_markers

# Generating real PDFs is not free, so keep documents small and example counts
# modest. The properties do not need large inputs to be falsified.
settled = settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _consecutive_groups(page_count: int, size: int) -> list[list[int]]:
    """Partition `range(page_count)` into consecutive runs of `size`, the last
    one short if it does not divide evenly. A test-only stand-in for the
    partitions `--pages` can produce, just shaped to be easy to generate here —
    the round-trip property below only needs *some* partition, not this one
    specifically."""
    return [
        list(range(start, min(start + size, page_count))) for start in range(0, page_count, size)
    ]


@given(
    page_count=st.integers(min_value=1, max_value=12),
    size=st.integers(min_value=1, max_value=6),
)
@settled
def test_split_then_merge_reproduces_the_original_order(page_count: int, size: int) -> None:
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        source = build_pdf(workspace / "source.pdf", page_count)

        with pikepdf.open(source) as pdf:
            pieces = [
                save_pdf(select_pages(pdf, group), workspace / f"piece{n}.pdf")
                for n, group in enumerate(_consecutive_groups(page_count, size))
            ]

        if len(pieces) == 1:
            assert page_markers(pieces[0]) == list(range(1, page_count + 1))
            return

        opened = [pikepdf.open(p) for p in pieces]
        try:
            rejoined = save_pdf(merge_documents(opened), workspace / "rejoined.pdf")
        finally:
            for pdf in opened:
                pdf.close()

        assert page_markers(rejoined) == list(range(1, page_count + 1))


@given(page_count=st.integers(min_value=1, max_value=10))
@settled
def test_identity_reorder_changes_nothing(page_count: int) -> None:
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        source = build_pdf(workspace / "source.pdf", page_count)

        with pikepdf.open(source) as pdf:
            out = save_pdf(select_pages(pdf, list(range(page_count))), workspace / "out.pdf")

        assert page_markers(out) == list(range(1, page_count + 1))


@given(data=st.data(), page_count=st.integers(min_value=1, max_value=10))
@settled
def test_a_permutation_followed_by_its_inverse_is_the_original(
    data: st.DataObject, page_count: int
) -> None:
    order = data.draw(st.permutations(range(page_count)))

    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        source = build_pdf(workspace / "source.pdf", page_count)

        with pikepdf.open(source) as pdf:
            shuffled = save_pdf(select_pages(pdf, list(order)), workspace / "shuffled.pdf")

        # Where each original page ended up, which is the inverse permutation.
        inverse = [order.index(position) for position in range(page_count)]
        with pikepdf.open(shuffled) as pdf:
            restored = save_pdf(select_pages(pdf, inverse), workspace / "restored.pdf")

        assert page_markers(restored) == list(range(1, page_count + 1))
