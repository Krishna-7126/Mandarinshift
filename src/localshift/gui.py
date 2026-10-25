"""
localshift.gui — Unified PySide6 Desktop GUI for LocalShift.

Workflows:
1. General File Converter: Multi-format batch file conversion (images, documents, PDFs).
2. PDF ↔ DOCX: Document interchange (PDF -> DOCX with OCR mode selection; DOCX -> PDF with renderer status).
3. PDF -> PNG/JPEG: PDF page rasterizer with configurable DPI, quality, page selection, and naming pattern.
4. Images -> PDF: Ordered multi-image assembly into a single PDF with layout/page sizing options.
5. PDF Workbench: Merge, Split, Extract, Reorder, and Rotate operations.

Backend isolation:
PySide6 is imported ONLY in this module. Backend modules (converter, formats, registry,
adapters, documents) do NOT depend on or import PySide6.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .converter import (
    ConversionCancelledError,
    ConversionError,
    ConversionRequest,
    convert_image,
    convert_images_to_pdf,
    convert_request,
)
from .documents.docx_renderer import DocxToPdfRenderer
from .documents.pdf_workbench import (
    extract_pdf_pages,
    merge_pdfs,
    reorder_pdf_pages,
    rotate_pdf_pages,
    split_pdf,
)
from .exceptions import InvalidInputError
from .formats import FORMAT_LABELS, input_format, output_formats_for

log = logging.getLogger(__name__)

# Primary LocalShift theme colors
COLOR_PRIMARY = "#4f46e5"
COLOR_PRIMARY_HOVER = "#4338ca"
COLOR_PRIMARY_ACTIVE = "#3730a3"
COLOR_BG = "#f8fafc"
COLOR_CARD = "#ffffff"
COLOR_BORDER = "#e2e8f0"
COLOR_TEXT = "#0f172a"
COLOR_MUTED = "#64748b"

STYLE_SHEET = f"""
QMainWindow {{
    background-color: {COLOR_BG};
}}
QWidget {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: {COLOR_TEXT};
}}
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_CARD};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background: #e2e8f0;
    color: {COLOR_MUTED};
    padding: 9px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {COLOR_CARD};
    color: {COLOR_PRIMARY};
    font-weight: 600;
    border-top: 2px solid {COLOR_PRIMARY};
}}
QTableWidget {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    gridline-color: #f1f5f9;
}}
QHeaderView::section {{
    background-color: #f1f5f9;
    color: {COLOR_MUTED};
    padding: 6px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
}}
QPushButton {{
    background-color: {COLOR_PRIMARY};
    color: white;
    padding: 7px 14px;
    border: none;
    border-radius: 5px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}
QPushButton:pressed {{
    background-color: {COLOR_PRIMARY_ACTIVE};
}}
QPushButton:disabled {{
    background-color: #94a3b8;
    color: #f1f5f9;
}}
QPushButton.secondary {{
    background-color: #f1f5f9;
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
}}
QPushButton.secondary:hover {{
    background-color: #e2e8f0;
}}
QLineEdit, QSpinBox, QComboBox {{
    background-color: white;
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLOR_PRIMARY};
}}
QGroupBox {{
    font-weight: 600;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {COLOR_TEXT};
}}
QProgressBar {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    text-align: center;
    background-color: #f1f5f9;
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {COLOR_PRIMARY};
    border-radius: 3px;
}}
"""


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Background Worker Threads
# ---------------------------------------------------------------------------

class BatchConversionWorker(QThread):
    """Executes a batch of conversions with cooperative cancellation."""
    item_done = Signal(int, str, str)  # index, status ("Done", "Failed", "Cancelled"), details/output
    progress = Signal(int, int)  # completed, total
    finished = Signal(int, int, list)  # succeeded, failed, errors

    def __init__(self, jobs: list[tuple[int, Path, str, Optional[Path], dict[str, Any]]]):
        super().__init__()
        self.jobs = jobs
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        succeeded = 0
        failed = 0
        errors: list[str] = []

        total = len(self.jobs)
        for completed_idx, (row_idx, source, target_fmt, outdir, options) in enumerate(self.jobs):
            if self._is_cancelled:
                self.item_done.emit(row_idx, "Cancelled", "Conversion cancelled by user.")
                failed += 1
                self.progress.emit(completed_idx + 1, total)
                continue

            try:
                req = ConversionRequest(
                    source=source,
                    target_format=target_fmt,
                    output_dir=outdir,
                    options=options,
                )
                res = convert_request(req, cancel_check=lambda: self._is_cancelled)
                succeeded += 1
                self.item_done.emit(row_idx, "Done", str(res.output_path))
            except ConversionCancelledError:
                failed += 1
                self.item_done.emit(row_idx, "Cancelled", "Operation cancelled.")
            except ConversionError as exc:
                failed += 1
                msg = str(exc)
                errors.append(f"{source.name}: {msg}")
                self.item_done.emit(row_idx, "Failed", msg)
            except Exception as exc:
                failed += 1
                msg = f"Unexpected error: {exc}"
                errors.append(f"{source.name}: {msg}")
                self.item_done.emit(row_idx, "Failed", msg)

            self.progress.emit(completed_idx + 1, total)

        self.finished.emit(succeeded, failed, errors)


class SingleTaskWorker(QThread):
    """Executes a single callable operation in the background."""
    progress = Signal(int, str)
    completed = Signal(bool, str, list)  # success, message, list of generated paths

    def __init__(self, task_fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.task_fn = task_fn
        self.args = args
        self.kwargs = kwargs
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            res = self.task_fn(*self.args, **self.kwargs)
            out_paths: list[str] = []
            if isinstance(res, (list, tuple)):
                out_paths = [str(p) for p in res]
                msg = f"Successfully generated {len(out_paths)} file(s)."
            elif isinstance(res, Path):
                out_paths = [str(res)]
                msg = f"Saved: {res}"
            else:
                msg = "Operation completed successfully."
            self.completed.emit(True, msg, out_paths)
        except ConversionCancelledError:
            self.completed.emit(False, "Operation was cancelled.", [])
        except ConversionError as exc:
            self.completed.emit(False, f"Operation failed: {exc}", [])
        except Exception as exc:
            self.completed.emit(False, f"Unexpected error: {exc}", [])


# ---------------------------------------------------------------------------
# Tab 1: General Batch File Converter
# ---------------------------------------------------------------------------

class FileConverterTab(QWidget):
    """Batch file conversion tab supporting multi-format queue and options."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.paths: list[Path] = []
        self.output_dir: Optional[Path] = None
        self.worker: Optional[BatchConversionWorker] = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Top Control Bar
        top_bar = QHBoxLayout()
        add_btn = QPushButton("Add Files…")
        add_btn.clicked.connect(self.pick_files)
        top_bar.addWidget(add_btn)
        self.add_btn = add_btn

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setProperty("class", "secondary")
        remove_btn.clicked.connect(self.remove_selected)
        top_bar.addWidget(remove_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self.clear_queue)
        top_bar.addWidget(clear_btn)

        top_bar.addStretch()

        self.output_btn = QPushButton("Output: Same folder as source")
        self.output_btn.setProperty("class", "secondary")
        self.output_btn.clicked.connect(self.pick_output)
        top_bar.addWidget(self.output_btn)

        layout.addLayout(top_bar)

        # Queue Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["File", "Size", "Convert to", "Status", "Details"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setAcceptDrops(True)
        self.table.dragEnterEvent = self.dragEnterEvent
        self.table.dropEvent = self.dropEvent
        layout.addWidget(self.table)

        # Options Box
        opt_box = QGroupBox("Batch Options (Applied when relevant)")
        opt_layout = QHBoxLayout(opt_box)
        opt_layout.setContentsMargins(10, 6, 10, 8)

        # PDF -> DOCX OCR option
        opt_layout.addWidget(QLabel("PDF OCR Mode:"))
        self.ocr_combo = QComboBox()
        self.ocr_combo.addItem("Auto (detect scanned)", "auto")
        self.ocr_combo.addItem("Native (text only)", "native")
        self.ocr_combo.addItem("Force OCR (all pages)", "force")
        opt_layout.addWidget(self.ocr_combo)

        opt_layout.addSpacing(16)

        # PDF -> Image DPI
        opt_layout.addWidget(QLabel("DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 400)
        self.dpi_spin.setValue(150)
        opt_layout.addWidget(self.dpi_spin)

        opt_layout.addSpacing(16)

        # Image Quality
        opt_layout.addWidget(QLabel("JPEG Quality:"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        opt_layout.addWidget(self.quality_spin)

        opt_layout.addSpacing(16)

        # Pages option
        opt_layout.addWidget(QLabel("Pages (PDF):"))
        self.pages_edit = QLineEdit("all")
        self.pages_edit.setPlaceholderText("e.g. all, 1-3, 5")
        self.pages_edit.setMaximumWidth(120)
        opt_layout.addWidget(self.pages_edit)

        opt_layout.addStretch()
        layout.addWidget(opt_box)

        # Bottom Bar
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_conversion)
        bottom.addWidget(self.cancel_btn)

        self.convert_btn = QPushButton("Convert Queue")
        self.convert_btn.clicked.connect(self.start_conversion)
        bottom.addWidget(self.convert_btn)

        layout.addLayout(bottom)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        self.add_paths(paths)
        event.acceptProposedAction()

    def pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add files for conversion",
            "",
            "Supported Files (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.pdf *.docx);;All Files (*.*)",
        )
        if paths:
            self.add_paths([Path(p) for p in paths])

    def pick_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if chosen:
            self.output_dir = Path(chosen)
            self.output_btn.setText(f"Output: {self.output_dir.name}")
            self.output_btn.setToolTip(str(self.output_dir))

    def add_paths(self, paths: Sequence[Path]) -> None:
        added_count = 0
        for path in paths:
            if not path.is_file() or path in self.paths:
                continue
            available_targets = output_formats_for(path)
            if not available_targets:
                continue

            self.paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Col 0: File Name
            name_item = QTableWidgetItem(path.name)
            name_item.setToolTip(str(path))
            self.table.setItem(row, 0, name_item)

            # Col 1: File Size
            try:
                size_str = _format_size(path.stat().st_size)
            except OSError:
                size_str = "—"
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 1, size_item)

            # Col 2: Target Format ComboBox
            combo = QComboBox()
            for fmt in available_targets:
                label = FORMAT_LABELS.get(fmt, fmt.upper())
                combo.addItem(f"{label} (.{fmt})", fmt)
            self.table.setCellWidget(row, 2, combo)

            # Col 3: Status
            status_item = QTableWidgetItem("Ready")
            self.table.setItem(row, 3, status_item)

            # Col 4: Details
            detail_item = QTableWidgetItem(str(path.parent))
            self.table.setItem(row, 4, detail_item)
            added_count += 1

        if added_count > 0:
            self.bar.setValue(0)

    def remove_selected(self) -> None:
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        for r in selected_rows:
            if 0 <= r < len(self.paths):
                self.paths.pop(r)
                self.table.removeRow(r)

    def clear_queue(self) -> None:
        self.paths.clear()
        self.table.setRowCount(0)
        self.bar.setValue(0)

    def start_conversion(self) -> None:
        if not self.paths:
            QMessageBox.information(self, "No files", "Add supported files to the queue first.")
            return

        jobs: list[tuple[int, Path, str, Optional[Path], dict[str, Any]]] = []
        for i, p in enumerate(self.paths):
            combo = self.table.cellWidget(i, 2)
            target_fmt = combo.currentData() if combo else None
            if not target_fmt:
                continue

            # Build options for this file
            opts: dict[str, Any] = {}
            if p.suffix.lower() == ".pdf" and target_fmt in ("png", "jpeg"):
                opts["dpi"] = self.dpi_spin.value()
                if target_fmt == "jpeg":
                    opts["quality"] = self.quality_spin.value()
                pages_val = self.pages_edit.text().strip()
                if pages_val and pages_val.lower() != "all":
                    opts["pages"] = pages_val
            elif target_fmt == "docx":
                opts["ocr_mode"] = self.ocr_combo.currentData()

            jobs.append((i, p, target_fmt, self.output_dir, opts))
            self.table.setItem(i, 3, QTableWidgetItem("Waiting…"))

        self.convert_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.bar.setValue(0)

        self.worker = BatchConversionWorker(jobs)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def cancel_conversion(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_item_done(self, row: int, status: str, detail: str) -> None:
        self.table.setItem(row, 3, QTableWidgetItem(status))
        self.table.setItem(row, 4, QTableWidgetItem(detail))

    def _on_progress(self, completed: int, total: int) -> None:
        pct = int((completed / total) * 100) if total > 0 else 0
        self.bar.setValue(pct)

    def _on_finished(self, succeeded: int, failed: int, errors: list[str]) -> None:
        self.convert_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        total = succeeded + failed
        if failed == 0:
            QMessageBox.information(
                self,
                "Conversion Complete",
                f"Successfully converted all {succeeded} file(s).",
            )
        else:
            err_summary = "\n".join(errors[:5])
            if len(errors) > 5:
                err_summary += f"\n… and {len(errors) - 5} more."
            QMessageBox.warning(
                self,
                "Completed with Issues",
                f"Completed: {succeeded}/{total} succeeded.\n{failed} failed.\n\nErrors:\n{err_summary}",
            )


# ---------------------------------------------------------------------------
# Tab 2: Document Interchange (PDF <-> DOCX)
# ---------------------------------------------------------------------------

class DocxInterchangeTab(QWidget):
    """Dedicated document conversion workflow between PDF and Microsoft Word (DOCX)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.worker: Optional[SingleTaskWorker] = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Mode Selection
        mode_box = QGroupBox("Interchange Direction")
        mode_layout = QHBoxLayout(mode_box)
        self.radio_pdf_to_docx = QRadioButton("PDF → DOCX (Document Extraction & OCR)")
        self.radio_pdf_to_docx.setChecked(True)
        self.radio_pdf_to_docx.toggled.connect(self._on_direction_changed)
        mode_layout.addWidget(self.radio_pdf_to_docx)

        self.radio_docx_to_pdf = QRadioButton("DOCX → PDF (Document Rendering)")
        self.radio_docx_to_pdf.toggled.connect(self._on_direction_changed)
        mode_layout.addWidget(self.radio_docx_to_pdf)
        layout.addWidget(mode_box)

        # Source File Picker
        src_box = QGroupBox("Source File")
        src_layout = QHBoxLayout(src_box)
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("Select input document…")
        src_layout.addWidget(self.src_edit)

        browse_btn = QPushButton("Browse…")
        browse_btn.setProperty("class", "secondary")
        browse_btn.clicked.connect(self.browse_source)
        src_layout.addWidget(browse_btn)
        layout.addWidget(src_box)

        # Options Container
        self.opts_box = QGroupBox("Conversion Settings")
        self.opts_layout = QVBoxLayout(self.opts_box)

        # PDF -> DOCX settings
        self.pdf_settings_widget = QWidget()
        ps_layout = QHBoxLayout(self.pdf_settings_widget)
        ps_layout.setContentsMargins(0, 0, 0, 0)
        ps_layout.addWidget(QLabel("OCR Engine Mode:"))
        self.ocr_mode_combo = QComboBox()
        self.ocr_mode_combo.addItem("Auto (detect scanned pages locally)", "auto")
        self.ocr_mode_combo.addItem("Native (fast digital text extraction only)", "native")
        self.ocr_mode_combo.addItem("Force OCR (run OCR on every page)", "force")
        ps_layout.addWidget(self.ocr_mode_combo)
        ps_layout.addStretch()
        self.opts_layout.addWidget(self.pdf_settings_widget)

        # DOCX -> PDF backend status
        self.docx_settings_widget = QWidget()
        ds_layout = QVBoxLayout(self.docx_settings_widget)
        ds_layout.setContentsMargins(0, 0, 0, 0)
        self.backend_status_label = QLabel()
        self._refresh_backend_status()
        ds_layout.addWidget(self.backend_status_label)
        self.docx_settings_widget.setVisible(False)
        self.opts_layout.addWidget(self.docx_settings_widget)

        layout.addWidget(self.opts_box)

        # Destination Folder
        dest_box = QGroupBox("Destination Folder")
        dest_layout = QHBoxLayout(dest_box)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Defaults to source document folder…")
        dest_layout.addWidget(self.dest_edit)

        dest_browse_btn = QPushButton("Choose…")
        dest_browse_btn.setProperty("class", "secondary")
        dest_browse_btn.clicked.connect(self.browse_destination)
        dest_layout.addWidget(dest_browse_btn)
        layout.addWidget(dest_box)

        layout.addStretch()

        # Bottom Bar
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.convert_btn = QPushButton("Convert Document")
        self.convert_btn.clicked.connect(self.execute_conversion)
        bottom.addWidget(self.convert_btn)

        layout.addLayout(bottom)

    def _refresh_backend_status(self) -> None:
        backend = DocxToPdfRenderer.find_available_backend()
        if backend == "word_com":
            self.backend_status_label.setText("✔ Active Rendering Backend: Microsoft Word COM Automation")
            self.backend_status_label.setStyleSheet("color: #15803d; font-weight: 500;")
        elif backend == "libreoffice":
            self.backend_status_label.setText("✔ Active Rendering Backend: LibreOffice Headless")
            self.backend_status_label.setStyleSheet("color: #15803d; font-weight: 500;")
        else:
            self.backend_status_label.setText(
                "⚠ No rendering backend available. Install LibreOffice or Microsoft Word to enable DOCX → PDF."
            )
            self.backend_status_label.setStyleSheet("color: #b91c1c; font-weight: 500;")

    def _on_direction_changed(self) -> None:
        is_pdf_to_docx = self.radio_pdf_to_docx.isChecked()
        self.pdf_settings_widget.setVisible(is_pdf_to_docx)
        self.docx_settings_widget.setVisible(not is_pdf_to_docx)
        if not is_pdf_to_docx:
            self._refresh_backend_status()

    def browse_source(self) -> None:
        is_pdf_to_docx = self.radio_pdf_to_docx.isChecked()
        filter_str = "PDF Documents (*.pdf)" if is_pdf_to_docx else "Word Documents (*.docx)"
        path, _ = QFileDialog.getOpenFileName(self, "Select Input Document", "", filter_str)
        if path:
            self.src_edit.setText(path)

    def browse_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.dest_edit.setText(folder)

    def execute_conversion(self) -> None:
        src_path_str = self.src_edit.text().strip()
        if not src_path_str:
            QMessageBox.warning(self, "Missing Input", "Please select a source document.")
            return

        source = Path(src_path_str)
        if not source.is_file():
            QMessageBox.warning(self, "Invalid File", f"Source file does not exist: {source}")
            return

        is_pdf_to_docx = self.radio_pdf_to_docx.isChecked()
        target_fmt = "docx" if is_pdf_to_docx else "pdf"

        out_dir = Path(self.dest_edit.text().strip()) if self.dest_edit.text().strip() else None

        options: dict[str, Any] = {}
        if is_pdf_to_docx:
            options["ocr_mode"] = self.ocr_mode_combo.currentData()

        self.convert_btn.setEnabled(False)
        self.bar.setRange(0, 0)  # indeterminate

        def _run():
            req = ConversionRequest(
                source=source,
                target_format=target_fmt,
                output_dir=out_dir,
                options=options,
            )
            res = convert_request(req)
            return res.output_path

        self.worker = SingleTaskWorker(_run)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def _on_completed(self, success: bool, msg: str, paths: list[str]) -> None:
        self.convert_btn.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)

        if success:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Conversion Failed", msg)


# ---------------------------------------------------------------------------
# Tab 3: PDF to Images (Rasterization)
# ---------------------------------------------------------------------------

class PdfRasterizeTab(QWidget):
    """Export PDF pages to high-resolution PNG or JPEG images."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.worker: Optional[SingleTaskWorker] = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Source PDF
        src_box = QGroupBox("Source PDF Document")
        src_layout = QHBoxLayout(src_box)
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("Select PDF to export as images…")
        src_layout.addWidget(self.src_edit)

        browse_btn = QPushButton("Browse…")
        browse_btn.setProperty("class", "secondary")
        browse_btn.clicked.connect(self.browse_pdf)
        src_layout.addWidget(browse_btn)
        layout.addWidget(src_box)

        # Rasterize Settings
        set_box = QGroupBox("Export Configuration")
        set_layout = QVBoxLayout(set_box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Output Format:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("PNG (Lossless)", "png")
        self.fmt_combo.addItem("JPEG (Compressed)", "jpeg")
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        row1.addWidget(self.fmt_combo)

        row1.addSpacing(20)
        row1.addWidget(QLabel("Resolution (DPI):"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 400)
        self.dpi_spin.setValue(150)
        row1.addWidget(self.dpi_spin)

        row1.addSpacing(20)
        self.quality_label = QLabel("JPEG Quality:")
        row1.addWidget(self.quality_label)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        self.quality_spin.setEnabled(False)  # initially PNG
        row1.addWidget(self.quality_spin)
        row1.addStretch()
        set_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Page Range:"))
        self.pages_edit = QLineEdit("all")
        self.pages_edit.setPlaceholderText("e.g. all, 1-3, 5")
        self.pages_edit.setMaximumWidth(140)
        row2.addWidget(self.pages_edit)

        row2.addSpacing(20)
        row2.addWidget(QLabel("Naming Pattern:"))
        self.pattern_edit = QLineEdit("{stem}_page_{page:02d}.{ext}")
        row2.addWidget(self.pattern_edit)
        set_layout.addLayout(row2)

        layout.addWidget(set_box)

        # Destination Folder
        dest_box = QGroupBox("Output Directory")
        dest_layout = QHBoxLayout(dest_box)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Defaults to source PDF folder…")
        dest_layout.addWidget(self.dest_edit)

        dest_btn = QPushButton("Choose…")
        dest_btn.setProperty("class", "secondary")
        dest_btn.clicked.connect(self.browse_dest)
        dest_layout.addWidget(dest_btn)
        layout.addWidget(dest_box)

        layout.addStretch()

        # Bottom Bar
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.export_btn = QPushButton("Export Pages")
        self.export_btn.clicked.connect(self.execute_export)
        bottom.addWidget(self.export_btn)
        layout.addLayout(bottom)

    def _on_format_changed(self) -> None:
        is_jpeg = self.fmt_combo.currentData() == "jpeg"
        self.quality_spin.setEnabled(is_jpeg)

    def browse_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF Document", "", "PDF Files (*.pdf)")
        if path:
            self.src_edit.setText(path)

    def browse_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.dest_edit.setText(folder)

    def execute_export(self) -> None:
        src_path_str = self.src_edit.text().strip()
        if not src_path_str:
            QMessageBox.warning(self, "Missing Input", "Please select a source PDF document.")
            return

        source = Path(src_path_str)
        if not source.is_file():
            QMessageBox.warning(self, "Invalid File", f"File does not exist: {source}")
            return

        fmt = self.fmt_combo.currentData()
        dpi = self.dpi_spin.value()
        quality = self.quality_spin.value()
        pages = self.pages_edit.text().strip() or "all"
        pattern = self.pattern_edit.text().strip() or "{stem}_page_{page:02d}.{ext}"
        out_dir = Path(self.dest_edit.text().strip()) if self.dest_edit.text().strip() else None

        options: dict[str, Any] = {
            "dpi": dpi,
            "pages": pages,
            "output_pattern": pattern,
        }
        if fmt == "jpeg":
            options["quality"] = quality

        self.export_btn.setEnabled(False)
        self.bar.setRange(0, 0)

        def _run():
            req = ConversionRequest(
                source=source,
                target_format=fmt,
                output_dir=out_dir,
                options=options,
            )
            res = convert_request(req)
            paths = getattr(res, "output_paths", ()) or (res.output_path,)
            return list(paths)

        self.worker = SingleTaskWorker(_run)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def _on_completed(self, success: bool, msg: str, paths: list[str]) -> None:
        self.export_btn.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)

        if success:
            QMessageBox.information(
                self,
                "Export Complete",
                f"{msg}\nExported {len(paths)} page image(s).",
            )
        else:
            QMessageBox.critical(self, "Export Failed", msg)


# ---------------------------------------------------------------------------
# Tab 4: Images to PDF (Ordered Assembly)
# ---------------------------------------------------------------------------

class ImagesToPdfTab(QWidget):
    """Combines multiple raster images into one ordered multipage PDF."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.image_paths: list[Path] = []
        self.worker: Optional[SingleTaskWorker] = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Controls Bar
        ctl_bar = QHBoxLayout()
        add_btn = QPushButton("Add Images…")
        add_btn.clicked.connect(self.pick_images)
        ctl_bar.addWidget(add_btn)

        up_btn = QPushButton("Move Up")
        up_btn.setProperty("class", "secondary")
        up_btn.clicked.connect(self.move_up)
        ctl_bar.addWidget(up_btn)

        down_btn = QPushButton("Move Down")
        down_btn.setProperty("class", "secondary")
        down_btn.clicked.connect(self.move_down)
        ctl_bar.addWidget(down_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("class", "secondary")
        remove_btn.clicked.connect(self.remove_selected)
        ctl_bar.addWidget(remove_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self.clear_all)
        ctl_bar.addWidget(clear_btn)

        ctl_bar.addStretch()
        layout.addLayout(ctl_bar)

        # Image List Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Order", "Filename", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAcceptDrops(True)
        self.table.dragEnterEvent = self.dragEnterEvent
        self.table.dropEvent = self.dropEvent
        layout.addWidget(self.table)

        # Layout & Formatting Options
        opts_box = QGroupBox("PDF Layout Options")
        opts_layout = QHBoxLayout(opts_box)

        opts_layout.addWidget(QLabel("Page Size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItem("Original Dimensions", "original")
        self.page_size_combo.addItem("A4", "a4")
        self.page_size_combo.addItem("Letter", "letter")
        opts_layout.addWidget(self.page_size_combo)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel("Fit Mode:"))
        self.fit_combo = QComboBox()
        self.fit_combo.addItem("Contain (no cropping)", "contain")
        self.fit_combo.addItem("Cover (fill page)", "cover")
        opts_layout.addWidget(self.fit_combo)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel("Orientation:"))
        self.orient_combo = QComboBox()
        self.orient_combo.addItem("Auto", "auto")
        self.orient_combo.addItem("Portrait", "portrait")
        self.orient_combo.addItem("Landscape", "landscape")
        opts_layout.addWidget(self.orient_combo)

        opts_layout.addSpacing(16)
        opts_layout.addWidget(QLabel("Margin (pt):"))
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 144)
        self.margin_spin.setValue(0)
        opts_layout.addWidget(self.margin_spin)

        opts_layout.addStretch()
        layout.addWidget(opts_box)

        # Output File Selector
        out_bar = QHBoxLayout()
        out_bar.addWidget(QLabel("Save PDF to:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Defaults to combined.pdf in first image's folder…")
        out_bar.addWidget(self.out_edit, stretch=1)

        choose_out_btn = QPushButton("Save As…")
        choose_out_btn.setProperty("class", "secondary")
        choose_out_btn.clicked.connect(self.choose_output_path)
        out_bar.addWidget(choose_out_btn)
        layout.addLayout(out_bar)

        # Bottom Bar
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.assemble_btn = QPushButton("Assemble PDF")
        self.assemble_btn.clicked.connect(self.execute_assembly)
        bottom.addWidget(self.assemble_btn)
        layout.addLayout(bottom)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        self.add_images(paths)
        event.acceptProposedAction()

    def pick_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Images for Assembly",
            "",
            "Raster Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All Files (*.*)",
        )
        if paths:
            self.add_images([Path(p) for p in paths])

    def add_images(self, paths: Sequence[Path]) -> None:
        for p in paths:
            if not p.is_file() or p in self.image_paths:
                continue
            fmt = input_format(p)
            if fmt in ("png", "jpeg", "webp", "bmp", "tiff"):
                self.image_paths.append(p)
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.image_paths))
        for i, p in enumerate(self.image_paths):
            order_item = QTableWidgetItem(f"#{i + 1}")
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, order_item)

            name_item = QTableWidgetItem(p.name)
            name_item.setToolTip(str(p))
            self.table.setItem(i, 1, name_item)

            try:
                size_str = _format_size(p.stat().st_size)
            except OSError:
                size_str = "—"
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 2, size_item)

    def move_up(self) -> None:
        row = self.table.currentRow()
        if row > 0:
            self.image_paths[row - 1], self.image_paths[row] = (
                self.image_paths[row],
                self.image_paths[row - 1],
            )
            self._refresh_table()
            self.table.setCurrentCell(row - 1, 1)

    def move_down(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.image_paths) - 1:
            self.image_paths[row + 1], self.image_paths[row] = (
                self.image_paths[row],
                self.image_paths[row + 1],
            )
            self._refresh_table()
            self.table.setCurrentCell(row + 1, 1)

    def remove_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.image_paths):
            self.image_paths.pop(row)
            self._refresh_table()

    def clear_all(self) -> None:
        self.image_paths.clear()
        self._refresh_table()
        self.bar.setValue(0)

    def choose_output_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save As PDF", "", "PDF Document (*.pdf)")
        if path:
            self.out_edit.setText(path)

    def execute_assembly(self) -> None:
        if not self.image_paths:
            QMessageBox.warning(self, "No Images", "Please add images to assemble.")
            return

        out_path_str = self.out_edit.text().strip()
        out_path = Path(out_path_str) if out_path_str else None

        options = {
            "page_size": self.page_size_combo.currentData(),
            "fit": self.fit_combo.currentData(),
            "orientation": self.orient_combo.currentData(),
            "margin": self.margin_spin.value(),
        }

        self.assemble_btn.setEnabled(False)
        self.bar.setRange(0, 0)

        def _run():
            return convert_images_to_pdf(self.image_paths, output_path=out_path, options=options)

        self.worker = SingleTaskWorker(_run)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def _on_completed(self, success: bool, msg: str, paths: list[str]) -> None:
        self.assemble_btn.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)

        if success:
            QMessageBox.information(self, "Assembly Complete", msg)
        else:
            QMessageBox.critical(self, "Assembly Failed", msg)


# ---------------------------------------------------------------------------
# Tab 5: PDF Workbench (Merge, Split, Extract, Reorder, Rotate)
# ---------------------------------------------------------------------------

class PdfWorkbenchTab(QWidget):
    """PDF Workbench providing Merge, Split, Extract, Reorder, and Rotate operations."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.merge_files: list[Path] = []
        self.worker: Optional[SingleTaskWorker] = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Operation Selector
        top_box = QGroupBox("Select PDF Workbench Operation")
        top_layout = QHBoxLayout(top_box)
        top_layout.addWidget(QLabel("Operation:"))
        self.op_combo = QComboBox()
        self.op_combo.addItem("Merge (combine multiple PDFs in order)", "merge")
        self.op_combo.addItem("Split (burst PDF into individual pages)", "split")
        self.op_combo.addItem("Extract (extract specific pages to a new PDF)", "extract")
        self.op_combo.addItem("Reorder (resequence pages in a PDF)", "reorder")
        self.op_combo.addItem("Rotate (rotate pages by 90°, 180°, or 270°)", "rotate")
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        top_layout.addWidget(self.op_combo, stretch=1)
        layout.addWidget(top_box)

        # Stacked / Dynamic Panels Container
        self.panels_container = QVBoxLayout()

        # 1. Merge Panel
        self.merge_widget = QWidget()
        mw_layout = QVBoxLayout(self.merge_widget)
        mw_layout.setContentsMargins(0, 0, 0, 0)
        mw_bar = QHBoxLayout()
        add_merge_btn = QPushButton("Add PDFs…")
        add_merge_btn.clicked.connect(self.pick_merge_pdfs)
        mw_bar.addWidget(add_merge_btn)

        up_btn = QPushButton("Move Up")
        up_btn.setProperty("class", "secondary")
        up_btn.clicked.connect(self.merge_move_up)
        mw_bar.addWidget(up_btn)

        down_btn = QPushButton("Move Down")
        down_btn.setProperty("class", "secondary")
        down_btn.clicked.connect(self.merge_move_down)
        mw_bar.addWidget(down_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setProperty("class", "secondary")
        remove_btn.clicked.connect(self.merge_remove)
        mw_bar.addWidget(remove_btn)
        mw_bar.addStretch()
        mw_layout.addLayout(mw_bar)

        self.merge_table = QTableWidget(0, 2)
        self.merge_table.setHorizontalHeaderLabels(["Order", "PDF File"])
        self.merge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.merge_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        mw_layout.addWidget(self.merge_table)
        self.panels_container.addWidget(self.merge_widget)

        # 2. Single Input File Operations (Split, Extract, Reorder, Rotate)
        self.single_widget = QWidget()
        sw_layout = QVBoxLayout(self.single_widget)
        sw_layout.setContentsMargins(0, 0, 0, 0)

        # Input PDF line
        in_bar = QHBoxLayout()
        in_bar.addWidget(QLabel("Input PDF:"))
        self.single_input_edit = QLineEdit()
        self.single_input_edit.setPlaceholderText("Select input PDF file…")
        in_bar.addWidget(self.single_input_edit, stretch=1)
        browse_in_btn = QPushButton("Browse…")
        browse_in_btn.setProperty("class", "secondary")
        browse_in_btn.clicked.connect(self.browse_single_input)
        in_bar.addWidget(browse_in_btn)
        sw_layout.addLayout(in_bar)

        # Split Controls
        self.split_box = QGroupBox("Split Options")
        sb_layout = QHBoxLayout(self.split_box)
        sb_layout.addWidget(QLabel("Pages to Split:"))
        self.split_pages_edit = QLineEdit("all")
        self.split_pages_edit.setPlaceholderText("all, 1-3, 5")
        sb_layout.addWidget(self.split_pages_edit)
        sb_layout.addSpacing(16)
        sb_layout.addWidget(QLabel("Naming Pattern:"))
        self.split_pattern_edit = QLineEdit("{stem}_page_{page:02d}.pdf")
        sb_layout.addWidget(self.split_pattern_edit)
        sw_layout.addWidget(self.split_box)

        # Extract Controls
        self.extract_box = QGroupBox("Extract Options")
        eb_layout = QHBoxLayout(self.extract_box)
        eb_layout.addWidget(QLabel("Pages to Extract:"))
        self.extract_pages_edit = QLineEdit()
        self.extract_pages_edit.setPlaceholderText("e.g. 1-3, 5")
        eb_layout.addWidget(self.extract_pages_edit)
        sw_layout.addWidget(self.extract_box)

        # Reorder Controls
        self.reorder_box = QGroupBox("Reorder Options")
        rb_layout = QHBoxLayout(self.reorder_box)
        rb_layout.addWidget(QLabel("Page Sequence:"))
        self.reorder_edit = QLineEdit()
        self.reorder_edit.setPlaceholderText("e.g. 3, 1, 2")
        rb_layout.addWidget(self.reorder_edit)
        sw_layout.addWidget(self.reorder_box)

        # Rotate Controls
        self.rotate_box = QGroupBox("Rotate Options")
        rot_layout = QHBoxLayout(self.rotate_box)
        rot_layout.addWidget(QLabel("Angle:"))
        self.rotate_angle_combo = QComboBox()
        self.rotate_angle_combo.addItem("90° Clockwise", 90)
        self.rotate_angle_combo.addItem("180° Flip", 180)
        self.rotate_angle_combo.addItem("270° (90° Counter-Clockwise)", 270)
        rot_layout.addWidget(self.rotate_angle_combo)
        rot_layout.addSpacing(16)
        rot_layout.addWidget(QLabel("Pages:"))
        self.rotate_pages_edit = QLineEdit("all")
        self.rotate_pages_edit.setPlaceholderText("all, 1, 3")
        rot_layout.addWidget(self.rotate_pages_edit)
        self.rotate_relative_check = QCheckBox("Relative to existing")
        rot_layout.addWidget(self.rotate_relative_check)
        sw_layout.addWidget(self.rotate_box)

        self.panels_container.addWidget(self.single_widget)
        layout.addLayout(self.panels_container)

        # Output Path Bar
        out_bar = QHBoxLayout()
        self.dest_label = QLabel("Output PDF:")
        out_bar.addWidget(self.dest_label)
        self.workbench_dest_edit = QLineEdit()
        self.workbench_dest_edit.setPlaceholderText("Defaults to auto-named file in source folder…")
        out_bar.addWidget(self.workbench_dest_edit, stretch=1)
        dest_browse_btn = QPushButton("Choose…")
        dest_browse_btn.setProperty("class", "secondary")
        dest_browse_btn.clicked.connect(self.browse_workbench_dest)
        out_bar.addWidget(dest_browse_btn)
        layout.addLayout(out_bar)

        # Bottom Bar
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.run_btn = QPushButton("Execute Operation")
        self.run_btn.clicked.connect(self.execute_operation)
        bottom.addWidget(self.run_btn)
        layout.addLayout(bottom)

        self._on_op_changed()

    def _on_op_changed(self) -> None:
        op = self.op_combo.currentData()
        is_merge = op == "merge"
        self.merge_widget.setVisible(is_merge)
        self.single_widget.setVisible(not is_merge)

        self.split_box.setVisible(op == "split")
        self.extract_box.setVisible(op == "extract")
        self.reorder_box.setVisible(op == "reorder")
        self.rotate_box.setVisible(op == "rotate")

        if op == "split":
            self.dest_label.setText("Output Directory:")
            self.workbench_dest_edit.setPlaceholderText("Defaults to source PDF folder…")
        else:
            self.dest_label.setText("Output PDF:")
            self.workbench_dest_edit.setPlaceholderText("Defaults to auto-named file in source folder…")

    def pick_merge_pdfs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs to Merge", "", "PDF Files (*.pdf)")
        if paths:
            for p in paths:
                pth = Path(p)
                if pth.is_file() and pth not in self.merge_files:
                    self.merge_files.append(pth)
            self._refresh_merge_table()

    def _refresh_merge_table(self) -> None:
        self.merge_table.setRowCount(len(self.merge_files))
        for i, p in enumerate(self.merge_files):
            order_item = QTableWidgetItem(f"#{i + 1}")
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.merge_table.setItem(i, 0, order_item)

            name_item = QTableWidgetItem(p.name)
            name_item.setToolTip(str(p))
            self.merge_table.setItem(i, 1, name_item)

    def merge_move_up(self) -> None:
        row = self.merge_table.currentRow()
        if row > 0:
            self.merge_files[row - 1], self.merge_files[row] = (
                self.merge_files[row],
                self.merge_files[row - 1],
            )
            self._refresh_merge_table()
            self.merge_table.setCurrentCell(row - 1, 1)

    def merge_move_down(self) -> None:
        row = self.merge_table.currentRow()
        if 0 <= row < len(self.merge_files) - 1:
            self.merge_files[row + 1], self.merge_files[row] = (
                self.merge_files[row],
                self.merge_files[row + 1],
            )
            self._refresh_merge_table()
            self.merge_table.setCurrentCell(row + 1, 1)

    def merge_remove(self) -> None:
        row = self.merge_table.currentRow()
        if 0 <= row < len(self.merge_files):
            self.merge_files.pop(row)
            self._refresh_merge_table()

    def browse_single_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF Document", "", "PDF Files (*.pdf)")
        if path:
            self.single_input_edit.setText(path)

    def browse_workbench_dest(self) -> None:
        op = self.op_combo.currentData()
        if op == "split":
            folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
            if folder:
                self.workbench_dest_edit.setText(folder)
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Save Output PDF", "", "PDF Document (*.pdf)")
            if path:
                self.workbench_dest_edit.setText(path)

    def execute_operation(self) -> None:
        op = self.op_combo.currentData()
        dest_val = self.workbench_dest_edit.text().strip()
        dest_path = Path(dest_val) if dest_val else None

        if op == "merge":
            if len(self.merge_files) < 2:
                QMessageBox.warning(self, "Not Enough Files", "Please add at least 2 PDF files to merge.")
                return

            def _task():
                return merge_pdfs(self.merge_files, output_path=dest_path)

        else:
            in_val = self.single_input_edit.text().strip()
            if not in_val:
                QMessageBox.warning(self, "Missing Input", "Please select an input PDF file.")
                return
            src = Path(in_val)
            if not src.is_file():
                QMessageBox.warning(self, "Invalid File", f"File does not exist: {src}")
                return

            if op == "split":
                pages = self.split_pages_edit.text().strip() or "all"
                pattern = self.split_pattern_edit.text().strip() or "{stem}_page_{page:02d}.pdf"

                def _task():
                    return split_pdf(src, output_dir=dest_path, pages=pages, output_pattern=pattern)

            elif op == "extract":
                pages = self.extract_pages_edit.text().strip()
                if not pages:
                    QMessageBox.warning(self, "Missing Pages", "Please specify pages to extract (e.g. 1-3, 5).")
                    return

                def _task():
                    return extract_pdf_pages(src, output_path=dest_path, pages=pages)

            elif op == "reorder":
                seq_str = self.reorder_edit.text().strip()
                if not seq_str:
                    QMessageBox.warning(self, "Missing Order", "Please specify page sequence (e.g. 3, 1, 2).")
                    return
                try:
                    order = [int(x.strip()) for x in seq_str.split(",") if x.strip()]
                except ValueError:
                    QMessageBox.warning(self, "Invalid Format", "Page sequence must be comma-separated integers.")
                    return

                def _task():
                    return reorder_pdf_pages(src, page_order=order, output_path=dest_path)

            elif op == "rotate":
                angle = self.rotate_angle_combo.currentData()
                pages = self.rotate_pages_edit.text().strip() or "all"
                relative = self.rotate_relative_check.isChecked()

                def _task():
                    return rotate_pdf_pages(
                        src,
                        rotation=angle,
                        pages=pages,
                        output_path=dest_path,
                        relative=relative,
                    )
            else:
                return

        self.run_btn.setEnabled(False)
        self.bar.setRange(0, 0)

        self.worker = SingleTaskWorker(_task)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def _on_completed(self, success: bool, msg: str, paths: list[str]) -> None:
        self.run_btn.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)

        if success:
            QMessageBox.information(self, "Workbench Operation Complete", msg)
        else:
            QMessageBox.critical(self, "Operation Failed", msg)


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

def _find_app_icon() -> Optional[Path]:
    """Find the application icon path across development and frozen environments."""
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "assets" / "icon.png",
        Path(sys.executable).parent / "assets" / "icon.png",
        Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png",
        Path(__file__).resolve().parent.parent.parent / "assets" / "icon.ico",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


class MainWindow(QMainWindow):
    """LocalShift main desktop application window with dedicated workflow tabs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalShift — Offline Document & Image Converter")
        self.resize(920, 620)
        self.setStyleSheet(STYLE_SHEET)

        icon_path = _find_app_icon()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header Title
        title_bar = QHBoxLayout()
        title_label = QLabel("LocalShift")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {COLOR_PRIMARY};")
        title_bar.addWidget(title_label)

        subtitle = QLabel("•  100% Offline  •  Zero Telemetry  •  Originals Stay Untouched")
        subtitle.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 12px; margin-top: 4px;")
        title_bar.addWidget(subtitle)
        title_bar.addStretch()
        layout.addLayout(title_bar)

        # Tab Widget for Workflows
        self.tabs = QTabWidget()
        self.convert_tab = FileConverterTab()
        self.docx_tab = DocxInterchangeTab()
        self.rasterize_tab = PdfRasterizeTab()
        self.assembly_tab = ImagesToPdfTab()
        self.workbench_tab = PdfWorkbenchTab()

        self.tabs.addTab(self.convert_tab, "File Converter")
        self.tabs.addTab(self.docx_tab, "PDF ↔ DOCX")
        self.tabs.addTab(self.rasterize_tab, "PDF → Images")
        self.tabs.addTab(self.assembly_tab, "Images → PDF")
        self.tabs.addTab(self.workbench_tab, "PDF Workbench")

        layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        # Route dropped files to current active tab if supported
        current_widget = self.tabs.currentWidget()
        if hasattr(current_widget, "dropEvent"):
            current_widget.dropEvent(event)


def main() -> None:
    """Launch the LocalShift desktop graphical user interface."""
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
