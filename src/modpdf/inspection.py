"""Reporting what is actually inside a PDF.

Most people have no way of knowing what a PDF contains beyond the pages they
can see, and a PDF can contain a great deal more: JavaScript that runs on open,
actions that launch programs or call home to a web server, whole files bundled
invisibly inside it, and — the one that catches out governments and law firms
alike — earlier revisions of the document that are still recoverable because
the editor appended changes instead of rewriting the file.

So `inspect` exists to answer "what am I actually about to send someone?". It
reads and reports; it changes nothing. Each finding says what was found and,
in plain language, why it is worth knowing, because "OpenAction: present" is
useless to the person who most needs to be told.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pikepdf

from modpdf.document import open_pdf
from modpdf.security.fs import resolve_input

__all__ = [
    "Concern",
    "Inspection",
    "count_revisions",
    "inspect_document",
    "scan_objects",
]

# Actions a PDF can ask a reader to perform, and why each one matters to
# somebody about to forward the file.
RISKY_ACTIONS: dict[str, str] = {
    "/JavaScript": "runs code when the document is opened or interacted with",
    "/Launch": "asks your PDF reader to run a program on your computer",
    "/URI": "contacts a web address, which can reveal when and where you opened the file",
    "/GoToR": "opens a different file, possibly over the network",
    "/SubmitForm": "sends form data to a server",
    "/ImportData": "reads data from a file on your computer",
}

# Metadata fields that name a person or their software.
IDENTIFYING_METADATA = ("/Author", "/Creator", "/Producer")


@dataclass(frozen=True)
class Concern:
    """Something a person forwarding this document would want to know."""

    label: str
    detail: str
    why: str


@dataclass(frozen=True)
class Inspection:
    """Everything `inspect` found. Serialises cleanly for --json."""

    path: Path
    size_bytes: int
    pdf_version: str
    page_count: int
    linearized: bool
    encrypted: bool
    permissions: dict[str, bool] = field(default_factory=dict)
    revisions: int = 1
    metadata: dict[str, str] = field(default_factory=dict)
    has_xmp: bool = False
    javascript: int = 0
    has_open_action: bool = False
    actions: dict[str, int] = field(default_factory=dict)
    embedded_files: tuple[str, ...] = ()
    xfa: bool = False
    uris: tuple[str, ...] = ()
    image_count: int = 0
    fonts: tuple[str, ...] = ()
    repairs: tuple[str, ...] = ()

    @property
    def concerns(self) -> list[Concern]:
        """The findings worth putting in front of the user, most serious first."""
        found: list[Concern] = []

        if self.repairs:
            found.append(
                Concern(
                    "Damaged file",
                    f"{len(self.repairs)} repair"
                    f"{'s' if len(self.repairs) != 1 else ''} were needed to read it",
                    "This PDF is malformed and had to be reconstructed before it "
                    "could be read. Pages or content may be missing, and what you "
                    "see may not be what the sender intended.",
                )
            )

        if self.javascript:
            found.append(
                Concern(
                    "JavaScript",
                    f"{self.javascript} script {'entry' if self.javascript == 1 else 'entries'}",
                    "PDF JavaScript can run when the file is opened. It is the most "
                    "common way a PDF is used to attack the person reading it.",
                )
            )

        if self.has_open_action:
            found.append(
                Concern(
                    "Opens automatically",
                    "an /OpenAction is set",
                    "Something is set to happen the moment the document is opened, "
                    "without the reader choosing it.",
                )
            )

        for action, count in sorted(self.actions.items()):
            if action == "/JavaScript":
                continue  # already reported above, and more prominently
            found.append(
                Concern(
                    f"{action.lstrip('/')} action",
                    f"{count} occurrence{'s' if count != 1 else ''}",
                    RISKY_ACTIONS.get(action, "asks the reader's software to do something"),
                )
            )

        if self.embedded_files:
            listed = ", ".join(self.embedded_files[:5])
            more = (
                "" if len(self.embedded_files) <= 5 else f" and {len(self.embedded_files) - 5} more"
            )
            found.append(
                Concern(
                    "Embedded files",
                    f"{len(self.embedded_files)}: {listed}{more}",
                    "Whole files are bundled inside this PDF and travel with it. "
                    "They do not appear on any page.",
                )
            )

        if self.revisions > 1:
            found.append(
                Concern(
                    "Earlier revisions",
                    f"{self.revisions} revisions in one file",
                    "This document was saved by appending changes rather than "
                    "rewriting it, so previous versions are still inside. Text that "
                    "looks deleted may be recoverable.",
                )
            )

        if self.xfa:
            found.append(
                Concern(
                    "XFA form",
                    "present",
                    "An Adobe-specific dynamic form. What other readers display may "
                    "differ from what Adobe Reader displays.",
                )
            )

        if self.uris:
            listed = ", ".join(self.uris[:3])
            more = "" if len(self.uris) <= 3 else f" and {len(self.uris) - 3} more"
            found.append(
                Concern(
                    "Outbound links",
                    f"{len(self.uris)}: {listed}{more}",
                    "Addresses this document points at. A link fetched automatically "
                    "can act as a read receipt.",
                )
            )

        identifying = {k: v for k, v in self.metadata.items() if k in IDENTIFYING_METADATA}
        if identifying:
            described = ", ".join(f"{k.lstrip('/')}={v}" for k, v in sorted(identifying.items()))
            found.append(
                Concern(
                    "Identifying metadata",
                    described,
                    "The file names a person or the software they used. This is "
                    "usually harmless and occasionally not.",
                )
            )

        return found


def count_revisions(data: bytes) -> int:
    """How many times this file has been written to, from its end-of-file markers.

    Every save appends a ``%%EOF``. A file saved once has one; a file edited
    incrementally has one per edit, with all the earlier content still present.

    Linearized ("fast web view") files are the honest exception: they carry two
    markers by design, having been written in one pass. The caller knows whether
    the file is linearized and should not treat two markers as two revisions
    when it is.
    """
    return max(data.count(b"%%EOF"), 1)


def inspect_document(path: Path, *, password: str | None = None) -> Inspection:
    """Read a PDF and report what is in it, without modifying anything."""
    resolved = resolve_input(path)
    raw_markers = count_revisions(resolved.read_bytes())
    repairs: list[str] = []

    with open_pdf(resolved, password=password, on_damage=repairs.extend) as pdf:
        linearized = bool(getattr(pdf, "is_linearized", False))
        # A linearized file writes two markers in a single save, so the second
        # one is not evidence of an earlier revision.
        revisions = max(raw_markers - 1, 1) if linearized else raw_markers

        scan = scan_objects(pdf)

        return Inspection(
            path=resolved,
            size_bytes=resolved.stat().st_size,
            pdf_version=str(pdf.pdf_version),
            page_count=len(pdf.pages),
            linearized=linearized,
            encrypted=bool(pdf.is_encrypted),
            permissions=_permissions(pdf),
            revisions=revisions,
            metadata={str(k): str(v) for k, v in pdf.docinfo.items()},
            has_xmp="/Metadata" in pdf.Root,
            javascript=scan["javascript"],
            has_open_action="/OpenAction" in pdf.Root,
            actions=scan["actions"],
            embedded_files=tuple(scan["embedded_files"]),
            xfa=_has_xfa(pdf),
            uris=tuple(dict.fromkeys(scan["uris"])),
            image_count=scan["images"],
            fonts=tuple(sorted(set(scan["fonts"]))),
            repairs=tuple(repairs),
        )


def scan_objects(pdf: pikepdf.Pdf) -> dict[str, Any]:
    """Walk every object once, collecting everything that matters.

    One pass rather than several targeted lookups, because actions and embedded
    files can be attached almost anywhere — a page, an annotation, a form field,
    a bookmark — and chasing each location separately is how detections get
    missed.
    """
    actions: dict[str, int] = {}
    embedded_files: list[str] = []
    uris: list[str] = []
    fonts: list[str] = []
    javascript = 0
    image_ids: set[tuple[int, int]] = set()
    mask_ids: set[tuple[int, int]] = set()

    for obj in pdf.objects:
        # An image is a stream, never a plain dictionary, so it has to be
        # counted before the dictionary-only checks below skip it. A soft mask
        # is an image stream too, but it is part of another image, not a
        # picture of its own: counting it would count a transparent PNG twice.
        if isinstance(obj, pikepdf.Stream):
            if obj.get("/Subtype") == pikepdf.Name("/Image"):
                image_ids.add(obj.objgen)
                mask = obj.get("/SMask")
                if isinstance(mask, pikepdf.Stream):
                    mask_ids.add(mask.objgen)
            continue
        if not isinstance(obj, pikepdf.Dictionary):
            continue

        action_type = obj.get("/S")
        if action_type is not None:
            name = str(action_type)
            if name in RISKY_ACTIONS:
                actions[name] = actions.get(name, 0) + 1
            if name == "/JavaScript":
                javascript += 1

        if "/JS" in obj and str(obj.get("/S", "")) != "/JavaScript":
            # A JavaScript payload without the matching action type still runs.
            javascript += 1

        uri = obj.get("/URI")
        if uri is not None:
            uris.append(str(uri))

        object_type = obj.get("/Type")
        if object_type == pikepdf.Name("/Filespec"):
            embedded_files.append(str(obj.get("/UF") or obj.get("/F") or "(unnamed)"))
        elif object_type == pikepdf.Name("/Font"):
            base = obj.get("/BaseFont")
            if base is not None:
                fonts.append(str(base).lstrip("/"))

    return {
        "actions": actions,
        "embedded_files": embedded_files,
        "uris": uris,
        "fonts": fonts,
        "javascript": javascript,
        "images": len(image_ids - mask_ids),
    }


def _permissions(pdf: pikepdf.Pdf) -> dict[str, bool]:
    """Which operations the document's encryption claims to allow.

    Worth a caveat that the report repeats: these are requests, not
    enforcement. Any reader is free to ignore them, and most tools do.
    """
    if not pdf.is_encrypted:
        return {}
    allow = pdf.allow
    return {
        name: bool(getattr(allow, name))
        for name in (
            "accessibility",
            "extract",
            "modify_annotation",
            "modify_assembly",
            "modify_form",
            "modify_other",
            "print_lowres",
            "print_highres",
        )
    }


def _has_xfa(pdf: pikepdf.Pdf) -> bool:
    form = pdf.Root.get("/AcroForm")
    return isinstance(form, pikepdf.Dictionary) and "/XFA" in form
