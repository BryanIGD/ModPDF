"""The main window.

Every action here ends in a call to `modpdf.tasks`. The window decides what to
ask and what to show; it never decides what a PDF is.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modpdf import tasks
from modpdf.document import EncryptedDocumentError
from modpdf.gui import session as session_module
from modpdf.gui import theme, workers
from modpdf.gui.grid import PAGE_ROLE, PageGrid
from modpdf.gui.session import Session, chunk_positions, positions_to_groups
from modpdf.gui.thumbnails import THUMBNAIL_WIDTH, ThumbnailRenderer, placeholder
from modpdf.gui.widgets import Chip, RangeRow, SectionLabel, mark_pixmap
from modpdf.ops.compress import DEFAULT_LEVEL, CompressReport, Level, Mode
from modpdf.ops.split import plan_pieces
from modpdf.security.fs import private_scratch_dir, synced_location

# Re-exported so callers need only one import to work with the grid.
__all__ = ["PAGE_ROLE", "MainWindow"]


class MainWindow(QMainWindow):
    """One document at a time, its pages, and what you can do to them."""

    session_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ModPDF")
        self.resize(1280, 860)
        self.setAcceptDrops(True)
        self.setStyleSheet(theme.stylesheet())

        self.session: Session | None = None
        self._thumbnails: dict[int, QPixmap] = {}
        self._busy = False
        # Lazily created the first time opening a second file combines more
        # than one file into this window's workspace; removed whole when the
        # window closes.
        self._workspace_dir: Path | None = None

        self._build_chrome()
        self._start_renderer()

        QShortcut(QKeySequence.StandardKey.Open, self, self.choose_file)
        QShortcut(QKeySequence.StandardKey.SaveAs, self, self.save_as)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, self.delete_selected)

    # ---------------------------------------------------------------- chrome

    def _build_chrome(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        column.addWidget(self._build_header())
        column.addWidget(self._build_toolbar())

        body = QWidget()
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_state())
        self.stack.addWidget(self._build_grid())
        body_row.addWidget(self.stack, 1)
        body_row.addWidget(self._build_inspector())
        column.addWidget(body, 1)

        column.addWidget(self._build_status_bar())
        self._refresh()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(52)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        mark = QLabel()
        mark.setPixmap(mark_pixmap(19))
        row.addWidget(mark)

        wordmark = QLabel(
            f'<span style="color:{theme.SLATE};font-weight:700;">Mod</span>'
            f'<span style="color:{theme.BLUE};font-weight:700;">PDF</span>'
        )
        wordmark.setStyleSheet("font-size: 14px;")
        row.addWidget(wordmark)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {theme.LINE};")
        row.addWidget(divider)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        row.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setStyleSheet(f"color: {theme.INK_3}; font-size: 12px;")
        row.addWidget(self.subtitle_label)

        row.addStretch(1)

        self.safety_chip = Chip()
        row.addWidget(self.safety_chip)

        self.review_button = QPushButton("Review")
        self.review_button.clicked.connect(lambda: self._show_panel("findings"))
        self.review_button.hide()
        row.addWidget(self.review_button)
        return header

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(46)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(4)

        self.open_button = QPushButton("Open")
        self.open_button.setToolTip(
            "Open a PDF, or — with one already open — add its pages onto the end"
        )
        self.open_button.clicked.connect(self.choose_file)
        row.addWidget(self.open_button)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {theme.LINE};")
        row.addWidget(divider)

        self.tool_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("pages", "Pages"),
            ("split", "Split"),
            ("compress", "Compress"),
            ("sanitize", "Sanitize"),
            ("findings", "What is in this file"),
        ):
            button = QPushButton(label)
            button.setObjectName("Tool")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, k=key: self._show_panel(k))
            self.tool_buttons[key] = button
            row.addWidget(button)

        row.addStretch(1)
        self.hint_label = QLabel("drag to reorder")
        self.hint_label.setStyleSheet(f"color: {theme.INK_3}; font-size: 11.5px;")
        row.addWidget(self.hint_label)
        return bar

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)

        mark = QLabel()
        mark.setPixmap(mark_pixmap(76))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)

        heading = QLabel("Drop a PDF here")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(heading)

        blurb = QLabel(
            "Nothing is uploaded and nothing is changed until you save.\n"
            "There is no recent-files list: a list of paths to confidential\n"
            "documents is itself a leak."
        )
        blurb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blurb.setStyleSheet(f"color: {theme.INK_2}; font-size: 12.5px;")
        layout.addWidget(blurb)

        choose = QPushButton("Choose a file…")
        choose.setObjectName("Primary")
        choose.clicked.connect(self.choose_file)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(choose)
        holder.addStretch(1)
        layout.addLayout(holder)
        return page

    def _build_grid(self) -> QWidget:
        self.grid = PageGrid(THUMBNAIL_WIDTH)
        self.grid.itemSelectionChanged.connect(self._refresh)
        self.grid.pages_moved.connect(self._pages_moved)
        return self.grid

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Inspector")
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.panels = QStackedWidget()
        self.panel_index = {
            "pages": self.panels.addWidget(self._build_pages_panel()),
            "split": self.panels.addWidget(self._build_split_panel()),
            "compress": self.panels.addWidget(self._build_compress_panel()),
            "sanitize": self.panels.addWidget(self._build_sanitize_panel()),
            "findings": self.panels.addWidget(self._build_findings_panel()),
        }
        layout.addWidget(self.panels, 1)

        footer = QFrame()
        footer.setStyleSheet(
            f"background: {theme.SURFACE}; border-top: 1px solid {theme.LINE_SOFT};"
        )
        footer_column = QVBoxLayout(footer)
        footer_column.setContentsMargins(18, 12, 18, 12)
        offline = QLabel("Offline")
        offline.setStyleSheet(f"color: {theme.BLUE}; font-size: 11.5px; font-weight: 600;")
        footer_column.addWidget(offline)
        note = QLabel("This app blocked its own network access at startup.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.INK_3}; font-size: 11px;")
        footer_column.addWidget(note)
        layout.addWidget(footer)
        return panel

    def _panel_shell(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        return page, layout

    def _build_pages_panel(self) -> QWidget:
        page, layout = self._panel_shell()
        layout.addWidget(SectionLabel("Document"))
        self.document_facts = QLabel()
        self.document_facts.setWordWrap(True)
        self.document_facts.setStyleSheet(f"color: {theme.INK_2}; font-size: 12.5px;")
        layout.addWidget(self.document_facts)

        layout.addSpacing(8)
        layout.addWidget(SectionLabel("With the selected pages"))

        self.extract_button = QPushButton("Extract to a new file…")
        self.extract_button.clicked.connect(self.extract_selected)
        layout.addWidget(self.extract_button)

        self.delete_button = QPushButton("Delete from document")
        self.delete_button.clicked.connect(self.delete_selected)
        layout.addWidget(self.delete_button)

        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        layout.addWidget(self.duplicate_button)

        layout.addSpacing(6)
        note = QLabel("Nothing is written until you save. The file on disk is untouched.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.INK_3}; font-size: 11.5px;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_split_panel(self) -> QWidget:
        page, layout = self._panel_shell()
        layout.addWidget(SectionLabel("How to divide it"))

        self._range_rows: list[RangeRow] = []
        self.split_mode = QButtonGroup(page)

        every_row = QHBoxLayout()
        self.split_every_radio = QRadioButton("Every")
        self.split_every_radio.setChecked(True)
        self.split_mode.addButton(self.split_every_radio)
        every_row.addWidget(self.split_every_radio)
        self.split_size = QSpinBox()
        self.split_size.setRange(1, 10000)
        self.split_size.setValue(10)
        self.split_size.valueChanged.connect(self._refresh_split_preview)
        every_row.addWidget(self.split_size)
        every_row.addWidget(QLabel("pages"))
        every_row.addStretch(1)
        layout.addLayout(every_row)

        self.split_ranges_radio = QRadioButton("Choose ranges")
        self.split_mode.addButton(self.split_ranges_radio)
        layout.addWidget(self.split_ranges_radio)
        self.split_mode.buttonClicked.connect(self._split_mode_changed)

        self.ranges_container = QWidget()
        self.ranges_layout = QVBoxLayout(self.ranges_container)
        self.ranges_layout.setContentsMargins(20, 4, 0, 4)
        self.ranges_layout.setSpacing(6)
        layout.addWidget(self.ranges_container)

        self.add_range_button = QPushButton("+ Add range")
        self.add_range_button.clicked.connect(lambda: self._add_range_row())
        add_row = QHBoxLayout()
        add_row.setContentsMargins(20, 0, 0, 0)
        add_row.addWidget(self.add_range_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)
        self._set_ranges_visible(False)

        layout.addSpacing(8)
        layout.addWidget(SectionLabel("Will write"))
        self.split_preview = QLabel()
        self.split_preview.setWordWrap(True)
        self.split_preview.setStyleSheet(
            f"color: {theme.INK_2}; font-size: 11.5px; font-family: {theme.mono_family()};"
        )
        layout.addWidget(self.split_preview)
        layout.addStretch(1)

        button = QPushButton("Choose folder…")
        button.setObjectName("Primary")
        button.clicked.connect(self.split_document)
        layout.addWidget(button)
        return page

    def _build_compress_panel(self) -> QWidget:
        page, layout = self._panel_shell()
        layout.addWidget(SectionLabel("How to compress it"))

        self.compress_mode = QButtonGroup(page)

        self.compress_visual_radio = QRadioButton("Visually lossless")
        self.compress_visual_radio.setChecked(True)
        self.compress_mode.addButton(self.compress_visual_radio)
        layout.addWidget(self.compress_visual_radio)
        visual_hint = QLabel(
            "Oversized images are downsampled. Text and vector art are never touched."
        )
        visual_hint.setWordWrap(True)
        visual_hint.setStyleSheet(
            f"color: {theme.INK_3}; font-size: 11px; padding-left: 22px; padding-bottom: 4px;"
        )
        layout.addWidget(visual_hint)

        self.compress_lossless_radio = QRadioButton("Lossless only")
        self.compress_mode.addButton(self.compress_lossless_radio)
        layout.addWidget(self.compress_lossless_radio)
        lossless_hint = QLabel("Not one pixel changes. Usually saves 5-25%.")
        lossless_hint.setWordWrap(True)
        lossless_hint.setStyleSheet(f"color: {theme.INK_3}; font-size: 11px; padding-left: 22px;")
        layout.addWidget(lossless_hint)

        layout.addSpacing(8)
        layout.addWidget(SectionLabel("Compression level"))

        self.compress_level_container = QWidget()
        level_layout = QVBoxLayout(self.compress_level_container)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setSpacing(2)

        self.compress_level = QButtonGroup(page)

        def level_row(label: str, hint: str) -> QRadioButton:
            radio = QRadioButton(label)
            self.compress_level.addButton(radio)
            level_layout.addWidget(radio)
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet(
                f"color: {theme.INK_3}; font-size: 11px; padding-left: 22px; padding-bottom: 4px;"
            )
            level_layout.addWidget(hint_label)
            return radio

        self.compress_quality_radio = level_row(
            "Best quality", "Least compression; only very oversized images shrink."
        )
        self.compress_balanced_radio = level_row(
            "Balanced", "Good compression with no visible difference. Recommended."
        )
        self.compress_maximum_radio = level_row(
            "Maximum compression", "Smallest file; photos may look visibly softer."
        )
        self._level_radios: dict[Level, QRadioButton] = {
            "low": self.compress_quality_radio,
            "balanced": self.compress_balanced_radio,
            "high": self.compress_maximum_radio,
        }
        self._level_radios[DEFAULT_LEVEL].setChecked(True)

        layout.addWidget(self.compress_level_container)
        # A disabled parent disables every child in Qt, so this one connection
        # covers all three radios the same way a single spin box was enabled
        # or disabled before.
        self.compress_visual_radio.toggled.connect(self.compress_level_container.setEnabled)

        layout.addSpacing(6)
        gate_note = QLabel(
            "Every page is checked against the original before being kept. If a "
            "page looks different enough to matter, the whole document falls back "
            "to the lossless result instead — the worst case is a file smaller "
            "than hoped for, never one that looks worse."
        )
        gate_note.setWordWrap(True)
        gate_note.setStyleSheet(f"color: {theme.INK_3}; font-size: 11px;")
        layout.addWidget(gate_note)

        layout.addSpacing(10)
        self.compress_result = QLabel()
        self.compress_result.setWordWrap(True)
        self.compress_result.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.compress_result)
        layout.addStretch(1)

        button = QPushButton("Compress and save…")
        button.setObjectName("Primary")
        button.clicked.connect(self.compress_document)
        layout.addWidget(button)
        return page

    def _build_sanitize_panel(self) -> QWidget:
        page, layout = self._panel_shell()
        layout.addWidget(SectionLabel("Clean this file"))
        blurb = QLabel(
            "Writes a new copy with the machinery removed — scripts, automatic "
            "actions, embedded files, earlier revisions and metadata. The pages "
            "and their text are untouched."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet(f"color: {theme.INK_2}; font-size: 12.5px;")
        layout.addWidget(blurb)

        layout.addSpacing(6)
        warning = QLabel(
            "<b>This is not redaction.</b> Text that is visible on a page stays "
            "there, including anything hidden under a black rectangle."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"background: {theme.BAD_SOFT}; border: 1px solid {theme.BAD_LINE};"
            f" border-radius: 7px; padding: 11px; color: {theme.BAD}; font-size: 11.5px;"
        )
        layout.addWidget(warning)
        layout.addStretch(1)

        button = QPushButton("Clean and save…")
        button.setObjectName("Primary")
        button.clicked.connect(self.sanitize_document)
        layout.addWidget(button)
        return page

    def _build_findings_panel(self) -> QWidget:
        page, layout = self._panel_shell()
        layout.addWidget(SectionLabel("What is in this file"))
        self.findings_label = QLabel()
        self.findings_label.setWordWrap(True)
        self.findings_label.setTextFormat(Qt.TextFormat.RichText)
        self.findings_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.findings_label, 1)
        return page

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(44)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"color: {theme.INK_2}; font-size: 12px;")
        row.addWidget(self.status_label)
        row.addStretch(1)

        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self.revert)
        row.addWidget(self.revert_button)

        self.save_button = QPushButton("Save as…")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save_as)
        row.addWidget(self.save_button)
        return bar

    # ------------------------------------------------------------- rendering

    def _start_renderer(self) -> None:
        self._render_thread = QThread(self)
        self.renderer = ThumbnailRenderer()
        self.renderer.moveToThread(self._render_thread)
        self.renderer.rendered.connect(self._thumbnail_ready)
        self.renderer.failed.connect(self._say)
        self._render_thread.start()

    def _thumbnail_ready(self, index: int, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        self._thumbnails[index] = pixmap
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item.data(PAGE_ROLE) == index:
                item.setIcon(pixmap)

    # --------------------------------------------------------------- opening

    def choose_file(self) -> None:
        """The Open button. With nothing loaded yet, opens a file; with a
        document already open, adds another one onto the end of it instead —
        there is one button because that is one idea: bring this file into
        the workspace, wherever the workspace currently stands."""
        title = "Add a PDF" if self.session is not None else "Open a PDF"
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PDF documents (*.pdf)")
        if path:
            self.add_path(Path(path))

    def open_path(self, path: Path, password: str | None = None) -> None:
        self._set_busy(True, f"Opening {path.name}…")
        workers.run(
            session_module.load,
            path,
            password,
            on_done=self._loaded,
            on_failed=lambda exc: self._open_failed(path, exc),
            on_crashed=self._crashed,
        )

    def _loaded(self, session: Session) -> None:
        self.session = session
        self._thumbnails.clear()
        self._set_busy(False)

        self.renderer.open(str(session.path), session.password)
        self._reset_split_panel()
        self._populate_grid()
        self.stack.setCurrentIndex(1)
        self._show_panel("pages")

        if session.repairs:
            count = len(session.repairs)
            QMessageBox.warning(
                self,
                "This file is damaged",
                f"{session.path.name} had to be repaired before it could be read "
                f"({count} issue{'s' if count != 1 else ''}).\n\n"
                "It opened, but content may be missing or altered from what the "
                "sender intended.",
            )
        self._refresh()

    def _open_failed(self, path: Path, exc: Exception) -> None:
        self._set_busy(False)
        if isinstance(exc, EncryptedDocumentError) and "needs a password" in str(exc):
            password, accepted = QInputDialog.getText(
                self,
                "Password required",
                f"{path.name} is encrypted.",
                QLineEdit.EchoMode.Password,
            )
            if accepted and password:
                self.open_path(path, password)
            return
        QMessageBox.critical(self, "Cannot open this file", str(exc))

    def add_path(self, path: Path, password: str | None = None) -> None:
        """Open `path`, or add it onto the end of the current workspace.

        With nothing open yet there is nothing to add to, so this behaves
        exactly like a plain Open. Otherwise the two documents are combined —
        honouring any reordering or deletion already pending on the one that's
        open — and the combined result becomes the new workspace: open pdf1,
        choose pdf2 through the same Open button, and the workspace holds
        pdf1+pdf2.
        """
        session = self.session
        if session is None:
            self.open_path(path, password)
            return

        destination = self._next_workspace_path(session.path.stem, path.stem)
        self._set_busy(True, f"Adding {path.name}…")
        workers.run(
            tasks.append_document,
            session.path,
            session.order,
            path,
            destination,
            password=session.password,
            addition_password=password,
            overwrite=True,
            on_done=lambda result: self._added(result[0]),
            on_failed=lambda exc: self._add_failed(path, exc),
            on_crashed=self._crashed,
        )

    def _added(self, written: Path) -> None:
        # The combined file was just written by us, unencrypted — reuse the
        # normal opening path to load it as the new workspace, the same way a
        # freshly chosen file would be.
        self.open_path(written)

    def _add_failed(self, path: Path, exc: Exception) -> None:
        self._set_busy(False)
        if isinstance(exc, EncryptedDocumentError) and "needs a password" in str(exc):
            password, accepted = QInputDialog.getText(
                self,
                "Password required",
                f"{path.name} is encrypted.",
                QLineEdit.EchoMode.Password,
            )
            if accepted and password:
                self.add_path(path, password)
            return
        QMessageBox.critical(self, "Cannot add this file", str(exc))

    def _next_workspace_path(self, base_stem: str, addition_stem: str) -> Path:
        """Where to write the combined document for one Add.

        Named after both pieces, so the window title reads "pdf1+pdf2.pdf"
        rather than a scratch filename nobody chose — and each further Add
        keeps building on that name, since `base_stem` is already the result
        of the ones before it.
        """
        if self._workspace_dir is None:
            self._workspace_dir = private_scratch_dir()
        name = f"{base_stem}+{addition_stem}"
        if len(name) > 120:  # keep it sane after many additions
            name = f"{base_stem}+…+{addition_stem}"
        return self._workspace_dir / f"{name}.pdf"

    # ------------------------------------------------------------- the grid

    def _populate_grid(self) -> None:
        session = self.session
        if session is None:
            return

        self.grid.blockSignals(True)
        self.grid.clear()
        blank = placeholder()
        for position, page in enumerate(session.order):
            item = QListWidgetItem(f"{position + 1}")
            item.setData(PAGE_ROLE, page)
            item.setIcon(self._thumbnails.get(page, blank))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.grid.addItem(item)
        self.grid.blockSignals(False)

        for page in dict.fromkeys(session.order):
            if page not in self._thumbnails:
                self.renderer.render(page, THUMBNAIL_WIDTH)

        # Any edit changes how many pages there are; range spin boxes must
        # never let someone set an end beyond what the document now has.
        self._sync_range_maximums()

    def _pages_moved(self, positions: list[int], before: int) -> None:
        """A drag finished: move those pages into the gap they were dropped in."""
        session = self.session
        if session is None:
            return

        landed = session.move(positions, before)
        self._populate_grid()

        # Leave the pages the user just dragged selected, where they now are.
        for offset in range(len(positions)):
            item = self.grid.item(landed + offset)
            if item is not None:
                item.setSelected(True)
        self._refresh()

    def _selected_positions(self) -> list[int]:
        return sorted(index.row() for index in self.grid.selectedIndexes())

    # --------------------------------------------------------------- actions

    def delete_selected(self) -> None:
        session, chosen = self.session, self._selected_positions()
        if session is None or not chosen:
            return
        try:
            session.remove(chosen)
        except ValueError as exc:
            QMessageBox.information(self, "Cannot delete these pages", str(exc))
            return
        self._populate_grid()
        self._refresh()

    def duplicate_selected(self) -> None:
        session, chosen = self.session, self._selected_positions()
        if session is None or not chosen:
            return
        session.duplicate(chosen)
        self._populate_grid()
        self._refresh()

    def revert(self) -> None:
        if self.session is None:
            return
        self.session.revert()
        self._populate_grid()
        self._refresh()

    def extract_selected(self) -> None:
        session, chosen = self.session, self._selected_positions()
        if session is None or not chosen:
            return
        pages = [session.order[at] for at in chosen]
        destination = self._ask_destination(f"{session.path.stem}-extract.pdf")
        if destination is None:
            return
        self._set_busy(True, f"Writing {len(pages)} pages…")
        workers.run(
            tasks.extract_pages,
            session.path,
            pages,
            destination,
            password=session.password,
            overwrite=True,
            on_done=lambda path: self._wrote(path, f"{len(pages)} pages"),
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def save_as(self) -> None:
        session = self.session
        if session is None:
            return
        destination = self._ask_destination(session.path.name)
        if destination is None:
            return
        self._set_busy(True, "Saving…")
        workers.run(
            session.save_to,
            destination,
            overwrite=True,
            on_done=lambda path: self._wrote(path, f"{session.pages} pages"),
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def split_document(self) -> None:
        session = self.session
        if session is None:
            return
        groups = self._current_split_groups()
        if not groups:
            QMessageBox.information(self, "Nothing to split", "Add at least one page range first.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Where should the pieces go?")
        if not folder:
            return
        target = Path(folder)
        if not self._confirm_if_synced(target):
            return

        pieces = plan_pieces(session.path.stem, groups)
        self._set_busy(True, f"Writing {len(pieces)} files…")
        workers.run(
            tasks.split_document,
            session.path,
            pieces,
            target,
            password=session.password,
            overwrite=True,
            on_done=lambda paths: self._wrote(target, f"{len(paths)} files"),
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def sanitize_document(self) -> None:
        session = self.session
        if session is None:
            return
        destination = self._ask_destination(f"{session.path.stem}-clean.pdf")
        if destination is None:
            return
        self._set_busy(True, "Cleaning…")
        workers.run(
            tasks.sanitize_file,
            session.path,
            destination,
            password=session.password,
            overwrite=True,
            on_done=self._sanitized,
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def _sanitized(self, result: tuple[Path, object]) -> None:
        path, report = result
        removed = getattr(report, "anything_removed", False)
        self._set_busy(False)
        self._say(f"Cleaned → {path.name}" if removed else f"{path.name} was already clean")

    def compress_document(self) -> None:
        session = self.session
        if session is None:
            return
        destination = self._ask_destination(f"{session.path.stem}-compressed.pdf")
        if destination is None:
            return

        mode: Mode = "lossless" if self.compress_lossless_radio.isChecked() else "visual"
        level = self.compress_level_choice()
        self.compress_result.setText("")
        self._set_busy(True, "Compressing…")
        workers.run(
            tasks.compress_file,
            session.path,
            destination,
            mode=mode,
            level=level,
            password=session.password,
            overwrite=True,
            # `level` is captured here, at the moment the job is submitted,
            # rather than re-read from the radio buttons once it completes —
            # the user is free to change the selection while a compression is
            # still running, and the result shown must describe the job that
            # actually ran, not whatever is checked by the time it finishes.
            on_done=lambda result: self._compressed(result, level),
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def compress_level_choice(self) -> Level:
        for level, radio in self._level_radios.items():
            if radio.isChecked():
                return level
        return DEFAULT_LEVEL  # unreachable: a QButtonGroup always has one checked

    def _compressed(
        self, result: tuple[Path, CompressReport], level: Level = DEFAULT_LEVEL
    ) -> None:
        path, report = result
        self._set_busy(False)
        if report.already_optimal:
            self._say(f"{path.name} was already optimal")
        else:
            self._say(f"Compressed → {path.name}  ({report.savings_ratio * 100:.0f}% smaller)")
        self._show_compress_result(report, level)

    def _show_compress_result(self, report: CompressReport, level: Level = DEFAULT_LEVEL) -> None:
        if report.already_optimal:
            self.compress_result.setText(
                f'<span style="color:{theme.GOOD}; font-weight:600;">Already optimal</span><br>'
                f'<span style="color:{theme.INK_2}; font-size:11.5px;">'
                "Nothing here was worth rewriting.</span>"
            )
            return

        lines = [
            f'<span style="font-size:13px; font-weight:600;">'
            f"{_human_size(report.before_bytes)} → {_human_size(report.after_bytes)}</span> "
            f'<span style="color:{theme.GOOD}; font-weight:600;">'
            f"({report.savings_ratio * 100:.0f}% smaller)</span>"
        ]

        images = report.images
        if images.recompressed:
            lines.append(
                f'<span style="font-size:11.5px; color:{theme.INK_2};">'
                f"images: {images.recompressed} recompressed, {images.left_alone} left alone"
                f"   {_human_size(images.bytes_before)} → {_human_size(images.bytes_after)}</span>"
            )

        if report.pages_flattened:
            pages_word = "page" if report.pages_flattened == 1 else "pages"
            lines.append(
                f'<span style="font-size:11.5px; color:{theme.INK_2};">'
                f"vector: {report.pages_flattened} {pages_word} of complex vector art "
                "flattened to an image</span>"
            )

        if report.fell_back:
            lines.append(
                f'<span style="font-size:11.5px; color:{theme.WARN}; font-weight:600;">'
                "fell back to lossless</span><br>"
                f'<span style="font-size:11px; color:{theme.INK_3};">'
                f"{report.fallback_reason}</span>"
            )
        elif report.verify_result is not None and report.mode_used == "visual":
            lines.append(
                f'<span style="font-size:11.5px; color:{theme.GOOD};">'
                "quality check passed — text identical</span>"
            )

        if level == "high" and report.mode_used == "visual":
            note = (
                "maximum compression: image quality was reduced on purpose "
                "to shrink the file further"
            )
            if report.pages_flattened:
                note += " — text stays selectable even on a flattened page; only its vector art was"
            lines.append(f'<span style="font-size:11px; color:{theme.WARN};">{note}</span>')

        self.compress_result.setText("<br>".join(lines))

    # ------------------------------------------------------------- plumbing

    def _ask_destination(self, suggested: str) -> Path | None:
        """Ask where to write, then say so if that lands in a synced folder."""
        chosen, _ = QFileDialog.getSaveFileName(self, "Save as", suggested, "PDF documents (*.pdf)")
        if not chosen:
            return None
        destination = Path(chosen)
        if not self._confirm_if_synced(destination):
            return None
        return destination

    def _confirm_if_synced(self, destination: Path) -> bool:
        """Warn when the destination syncs to the cloud. Informs; does not refuse.

        ModPDF uploads nothing, but a file written into a Dropbox folder is
        uploaded within seconds all the same, and the user has no reason to be
        thinking about that while picking a folder.
        """
        found = synced_location(destination)
        if found is None:
            return True

        answer = QMessageBox.warning(
            self,
            f"{found.service} will upload this file",
            f"This folder syncs to {found.service}, so the document will be copied "
            f"to their servers within seconds of saving.\n\n"
            f"ModPDF does not upload anything — but saving here does.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Save

    def _wrote(self, path: Path, summary: str) -> None:
        self._set_busy(False)
        self._say(f"Wrote {summary} → {path.name}")

    def _failed(self, exc: Exception) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "That did not work", str(exc))

    def _crashed(self, trace: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(
            self,
            "Something went wrong",
            "This is a bug in ModPDF, not something you did.\n\n" + trace.strip().splitlines()[-1],
        )

    def _say(self, message: str) -> None:
        self.status_label.setText(message)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor) if busy else (
            QApplication.restoreOverrideCursor()
        )
        if message:
            self._say(message)
        self._refresh()

    def _show_panel(self, key: str) -> None:
        self.panels.setCurrentIndex(self.panel_index[key])
        for name, button in self.tool_buttons.items():
            button.setChecked(name == key)
        if key == "split":
            self._refresh_split_preview()

    def _split_mode_changed(self) -> None:
        self._set_ranges_visible(self.split_ranges_radio.isChecked())
        self._refresh_split_preview()

    def _set_ranges_visible(self, visible: bool) -> None:
        self.split_size.setEnabled(not visible)
        self.ranges_container.setVisible(visible)
        self.add_range_button.setVisible(visible)
        if visible and not self._range_rows:
            self._add_range_row()

    def _add_range_row(self) -> None:
        """Add a range row, defaulting to start right after the last one ends."""
        maximum = self.session.pages if self.session is not None else 1
        start = min(self._range_rows[-1].value()[1] + 1, maximum) if self._range_rows else 1
        row = RangeRow(maximum, start=start, end=start)
        row.changed.connect(self._refresh_split_preview)
        row.removed.connect(self._remove_range_row)
        self._range_rows.append(row)
        self.ranges_layout.addWidget(row)
        self._refresh_split_preview()

    def _remove_range_row(self, row: RangeRow) -> None:
        if len(self._range_rows) <= 1:
            return  # always leave at least one row: there must be something to split
        self._range_rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh_split_preview()

    def _reset_split_panel(self) -> None:
        """Called when a new document loads, so old ranges from a previous
        file are not silently reused against a document they no longer fit."""
        for row in list(self._range_rows):
            row.setParent(None)
            row.deleteLater()
        self._range_rows.clear()
        self.split_every_radio.setChecked(True)
        if self.session is not None:
            self.split_size.setValue(min(10, self.session.pages))
        self._set_ranges_visible(False)

    def _sync_range_maximums(self) -> None:
        """Keep range spin boxes from allowing more pages than currently exist."""
        if self.session is None:
            return
        for row in self._range_rows:
            row.set_maximum(self.session.pages)

    def _current_split_groups(self) -> list[list[int]]:
        """The pieces the current split settings would produce, as source indices.

        Counted against `session.order` — the document as the grid currently
        shows it — so a split after a drag divides the pages the way they now
        look, not the way the file on disk still is.
        """
        session = self.session
        if session is None:
            return []
        if self.split_ranges_radio.isChecked():
            ranges = [row.value() for row in self._range_rows]
            return positions_to_groups(session.order, ranges)
        return chunk_positions(session.order, self.split_size.value())

    def _refresh_split_preview(self) -> None:
        session = self.session
        if session is None:
            self.split_preview.setText("")
            return
        groups = self._current_split_groups()
        if not groups:
            self.split_preview.setText("Nothing to write yet.")
            return
        pieces = plan_pieces(session.path.stem, groups)
        shown = "\n".join(p.filename for p in pieces[:6])
        if len(pieces) > 6:
            shown += f"\n… and {len(pieces) - 6} more"
        self.split_preview.setText(f"{len(pieces)} files\n\n{shown}")

    def _refresh(self) -> None:
        session = self.session
        has_document = session is not None
        selected = len(self._selected_positions()) if has_document else 0

        for button in (self.extract_button, self.delete_button, self.duplicate_button):
            button.setEnabled(has_document and selected > 0 and not self._busy)
        self.save_button.setEnabled(has_document and not self._busy)
        self.revert_button.setEnabled(session is not None and session.modified and not self._busy)
        for button in self.tool_buttons.values():
            button.setEnabled(has_document)

        if session is None:
            self.title_label.setText("")
            self.subtitle_label.setText("No document open")
            self.safety_chip.hide()
            self.review_button.hide()
            self.hint_label.setText("")
            if not self._busy:
                self._say("")
            return

        self.title_label.setText(session.path.name)
        size_mb = session.inspection.size_bytes / 1_048_576
        self.subtitle_label.setText(f"{session.source_pages} pages · {size_mb:.1f} MB")
        self.hint_label.setText("drag to reorder")

        concerns = session.inspection.concerns
        if concerns:
            worst = "bad" if any("JavaScript" in c.label for c in concerns) else "warn"
            noun = "thing" if len(concerns) == 1 else "things"
            self.safety_chip.show_state(f"{len(concerns)} {noun} to know", tone=worst)
            self.review_button.show()
        else:
            self.safety_chip.show_state("Nothing notable", tone="good")
            self.review_button.hide()

        self.document_facts.setText(
            f"{session.source_pages} pages · {size_mb:.1f} MB · PDF "
            f"{session.inspection.pdf_version}<br>"
            f"{session.inspection.image_count} images · "
            f"{'encrypted' if session.inspection.encrypted else 'not encrypted'}"
        )
        self.findings_label.setText(self._findings_html(session))

        if not self._busy:
            state = f"{selected} of {session.pages} pages selected"
            if session.modified:
                dropped = session.dropped
                state += " · unsaved changes"
                if dropped:
                    state += f", {dropped} pages dropped"
            self._say(state)

    def _findings_html(self, session: Session) -> str:
        concerns = session.inspection.concerns
        if not concerns:
            return (
                f'<span style="color:{theme.GOOD};font-weight:600;">Nothing notable.</span>'
                f'<br><span style="color:{theme.INK_2};">No scripts, no embedded files, '
                "no automatic actions, and only one revision in the file.</span>"
            )
        blocks = []
        for concern in concerns:
            blocks.append(
                f'<p style="margin:0 0 12px 0;">'
                f'<span style="color:{theme.WARN};font-weight:600;">{concern.label}</span>'
                f'<span style="color:{theme.INK_3};"> — {concern.detail}</span><br>'
                f'<span style="color:{theme.INK_2};font-size:11.5px;">{concern.why}</span>'
                f"</p>"
            )
        return "".join(blocks)

    # ----------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")
        ]
        if not paths:
            return
        event.acceptProposedAction()
        if len(paths) == 1:
            self.add_path(paths[0])
        else:
            self._merge_dropped(paths)

    def _merge_dropped(self, paths: list[Path]) -> None:
        destination = self._ask_destination("merged.pdf")
        if destination is None:
            return
        self._set_busy(True, f"Merging {len(paths)} files…")
        workers.run(
            tasks.merge_files,
            paths,
            destination,
            overwrite=True,
            on_done=lambda result: self._wrote(result[0], f"{sum(result[1])} pages"),
            on_failed=self._failed,
            on_crashed=self._crashed,
        )

    def closeEvent(self, event: object) -> None:
        self.renderer.close()
        self._render_thread.quit()
        self._render_thread.wait(2000)
        if self._workspace_dir is not None:
            shutil.rmtree(self._workspace_dir, ignore_errors=True)
        super().closeEvent(event)  # type: ignore[arg-type]


def _human_size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
