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

from PySide6.QtCore import QPoint, Qt, QThread, Signal
from PySide6.QtGui import QColor, QCursor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
    QStackedWidget,
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
from .radial_menu import RadialConversionMenu, ShiftActivationFilter, is_shift_pressed
from .settings import get_settings, validate_destination_directory
from .shell_integration import (
    BackgroundGestureController,
    is_start_with_windows_enabled,
    set_start_with_windows_enabled,
)
from .documents.pdf_tool_registry import PdfToolRegistry
from .pdf_suite_ui import PdfToolExecutionDialog, PdfToolsSuiteTab

log = logging.getLogger(__name__)

# Primary LocalShift theme colors
COLOR_PRIMARY = "#6366f1"
COLOR_PRIMARY_HOVER = "#4f46e5"
COLOR_PRIMARY_ACTIVE = "#4338ca"
COLOR_BG = "#0b0f19"
COLOR_CARD = "#131d2e"
COLOR_BORDER = "#1e293b"
COLOR_TEXT = "#f8fafc"
COLOR_MUTED = "#94a3b8"

DARK_THEME_STYLESHEET = """
QMainWindow {
    background-color: #0b0f19;
}
QWidget {
    font-family: "Segoe UI Variable", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    color: #f8fafc;
}
#sidebar {
    background-color: #0f172a;
    border-right: 1px solid #1e293b;
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
}
#sidebar QLabel#brandTitle {
    font-size: 17px;
    font-weight: 700;
    color: #f8fafc;
}
QPushButton.sidebar-nav {
    background: transparent;
    color: #94a3b8;
    border: none;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 3px;
}
QPushButton.sidebar-nav:hover {
    background: rgba(255, 255, 255, 0.05);
    color: #f8fafc;
}
QPushButton.sidebar-nav[active="true"] {
    background: #1e293b;
    color: #818cf8;
    font-weight: 600;
    border-left: 3px solid #6366f1;
}
#bottomStatusCard {
    background-color: rgba(30, 41, 59, 0.5);
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 10px;
}
#dropLandingCard {
    border: 2px dashed #334155;
    border-radius: 14px;
    background-color: rgba(30, 41, 59, 0.35);
    padding: 20px;
}
#queueCard, #historyCard, #optCard {
    background-color: #161f30;
    border: 1px solid #1e293b;
    border-radius: 14px;
}
#shortcutCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4f46e5, stop:1 #0284c7);
    border-radius: 14px;
    padding: 16px;
    color: #ffffff;
}
QTabWidget::pane {
    border: none;
    background-color: transparent;
}
QTableWidget {
    background-color: #131d2e;
    border: 1px solid #1e293b;
    border-radius: 8px;
    gridline-color: #1e293b;
    selection-background-color: #312e81;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #0f172a;
    color: #94a3b8;
    padding: 8px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #1e293b;
}
QPushButton {
    background-color: #6366f1;
    color: #ffffff;
    padding: 8px 16px;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #4f46e5;
}
QPushButton:pressed {
    background-color: #4338ca;
}
QPushButton:disabled {
    background-color: #334155;
    color: #64748b;
}
QPushButton.secondary {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
}
QPushButton.secondary:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton.accent {
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #818cf8;
    font-weight: 700;
    border-radius: 20px;
}
QPushButton.accent:hover {
    background-color: #4338ca;
}
QPushButton.pill-cta {
    background-color: #4f46e5;
    color: #ffffff;
    border-radius: 20px;
    padding: 9px 20px;
    font-weight: 700;
    font-size: 14px;
}
QPushButton.pill-cta:hover {
    background-color: #4338ca;
}
QLineEdit, QSpinBox, QComboBox {
    background-color: #0b101b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 22px;
    color: #f8fafc;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #6366f1;
}
QComboBox QAbstractItemView {
    background-color: #131d2e;
    color: #f8fafc;
    selection-background-color: #4f46e5;
    border: 1px solid #334155;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #1e293b;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 14px;
    background-color: rgba(19, 29, 46, 0.4);
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    color: #cbd5e1;
}
QProgressBar {
    border: 1px solid #1e293b;
    border-radius: 6px;
    text-align: center;
    background-color: #0f172a;
    min-height: 18px;
    color: #f8fafc;
}
QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 5px;
}
"""

LIGHT_THEME_STYLESHEET = """
QMainWindow {
    background-color: #f1f5f9;
}
QWidget {
    font-family: "Segoe UI Variable", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    color: #0f172a;
}
#sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e2e8f0;
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
}
#sidebar QLabel#brandTitle {
    font-size: 17px;
    font-weight: 700;
    color: #0f172a;
}
QPushButton.sidebar-nav {
    background: transparent;
    color: #64748b;
    border: none;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 3px;
}
QPushButton.sidebar-nav:hover {
    background: #f8fafc;
    color: #0f172a;
}
QPushButton.sidebar-nav[active="true"] {
    background: #e0e7ff;
    color: #4f46e5;
    font-weight: 600;
    border-left: 3px solid #4f46e5;
}
#bottomStatusCard {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 10px;
}
#dropLandingCard {
    border: 2px dashed #cbd5e1;
    border-radius: 14px;
    background-color: #ffffff;
    padding: 20px;
}
#queueCard, #historyCard, #optCard {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}
#shortcutCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4f46e5, stop:1 #0284c7);
    border-radius: 14px;
    padding: 16px;
    color: #ffffff;
}
QTabWidget::pane {
    border: none;
    background-color: transparent;
}
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    gridline-color: #f1f5f9;
    selection-background-color: #e0e7ff;
    selection-color: #1e1b4b;
}
QHeaderView::section {
    background-color: #f8fafc;
    color: #64748b;
    padding: 8px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #e2e8f0;
}
QPushButton {
    background-color: #4f46e5;
    color: #ffffff;
    padding: 8px 16px;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #4338ca;
}
QPushButton:pressed {
    background-color: #3730a3;
}
QPushButton:disabled {
    background-color: #cbd5e1;
    color: #64748b;
}
QPushButton.secondary {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
}
QPushButton.secondary:hover {
    background-color: #f8fafc;
}
QPushButton.accent {
    background-color: #4f46e5;
    color: #ffffff;
    font-weight: 700;
    border-radius: 20px;
}
QPushButton.accent:hover {
    background-color: #4338ca;
}
QPushButton.pill-cta {
    background-color: #4f46e5;
    color: #ffffff;
    border-radius: 20px;
    padding: 9px 20px;
    font-weight: 700;
    font-size: 14px;
}
QPushButton.pill-cta:hover {
    background-color: #4338ca;
}
QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 22px;
    color: #0f172a;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #4f46e5;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 14px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    color: #0f172a;
}
QProgressBar {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    text-align: center;
    background-color: #f1f5f9;
    min-height: 18px;
    color: #0f172a;
}
QProgressBar::chunk {
    background-color: #4f46e5;
    border-radius: 5px;
}
"""

STYLE_SHEET = DARK_THEME_STYLESHEET

def _reveal_in_file_manager(path: Optional[Path]) -> None:
    """Reveal file or directory in Windows File Explorer or native file manager."""
    if not path:
        return
    try:
        p = Path(path).resolve()
        if sys.platform == "win32":
            if p.is_file():
                os.system(f'explorer /select,"{p}"')
            elif p.is_dir():
                os.startfile(str(p))
        else:
            folder = p if p.is_dir() else p.parent
            os.system(f'xdg-open "{folder}"')
    except Exception as exc:
        log.warning("Could not reveal in file manager: %s", exc)


def _open_file_externally(path: Optional[Path]) -> None:
    """Open converted file using the system default application."""
    if not path:
        return
    try:
        p = Path(path).resolve()
        if p.is_file():
            if sys.platform == "win32":
                os.startfile(str(p))
            else:
                os.system(f'xdg-open "{p}"')
    except Exception as exc:
        log.warning("Could not open file externally: %s", exc)


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
    """Batch file conversion tab supporting multi-format queue, options, and radial quick menu."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.paths: list[Path] = []
        self.output_dir: Optional[Path] = None
        self.worker: Optional[BatchConversionWorker] = None
        self._last_converted_paths: list[Path] = []
        self._radial_menu: Optional[RadialConversionMenu] = None
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------------
        # Left / Center Area: Drop Area, Queue Card, Options, Result Banner
        # -------------------------------------------------------------------
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)

        # 1. Drop Zone Landing Card (Mockup 1 & 2)
        self.landing_frame = QFrame()
        self.landing_frame.setObjectName("dropLandingCard")
        landing_box = QVBoxLayout(self.landing_frame)
        landing_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        landing_box.setSpacing(6)
        landing_box.setContentsMargins(16, 20, 16, 20)

        upload_icon = QLabel("☁")
        upload_icon.setStyleSheet("font-size: 28px; color: #818cf8;")
        upload_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        landing_box.addWidget(upload_icon)

        drop_title = QLabel("Drop files here, or browse")
        drop_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        landing_box.addWidget(drop_title)

        drop_sub = QLabel("PDF, DOCX, PNG, JPG, WebP, BMP, TIFF, GIF, ICO")
        drop_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        drop_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        landing_box.addWidget(drop_sub)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(10)
        self.browse_cta = QPushButton("Browse files")
        self.browse_cta.setProperty("class", "accent")
        self.browse_cta.clicked.connect(self.pick_files)
        btn_row.addWidget(self.browse_cta)

        self.radial_btn = QPushButton("Open Radial Menu")
        self.radial_btn.setProperty("class", "secondary")
        self.radial_btn.setToolTip("Open circular radial conversion menu (or press Shift)")
        self.radial_btn.clicked.connect(lambda: self.trigger_radial_menu())
        btn_row.addWidget(self.radial_btn)
        landing_box.addLayout(btn_row)

        center_layout.addWidget(self.landing_frame)

        # 2. Queue Card (Mockup 1 & 2)
        self.queue_card = QFrame()
        self.queue_card.setObjectName("queueCard")
        qc_layout = QVBoxLayout(self.queue_card)
        qc_layout.setContentsMargins(14, 12, 14, 12)
        qc_layout.setSpacing(8)

        # Queue Card Header
        qc_header = QHBoxLayout()
        self.queue_count_lbl = QLabel("Queue · 0 files")
        self.queue_count_lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        qc_header.addWidget(self.queue_count_lbl)

        qc_header.addStretch()

        self.add_btn = QPushButton("Add Files…")
        self.add_btn.setProperty("class", "secondary")
        self.add_btn.clicked.connect(self.pick_files)
        qc_header.addWidget(self.add_btn)

        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.setProperty("class", "secondary")
        self.remove_btn.clicked.connect(self.remove_selected)
        qc_header.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.setProperty("class", "secondary")
        self.clear_btn.clicked.connect(self.clear_queue)
        qc_header.addWidget(self.clear_btn)
        qc_layout.addLayout(qc_header)

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
        self.table.setMinimumHeight(150)
        qc_layout.addWidget(self.table)

        # Queue Card Bottom Bar: Destination status + Convert queue button
        qc_bottom = QHBoxLayout()
        qc_bottom.setContentsMargins(0, 4, 0, 0)
        self.dest_status_lbl = QLabel("Saved next to the originals")
        self.dest_status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        qc_bottom.addWidget(self.dest_status_lbl)

        self.output_btn = QPushButton("Change…")
        self.output_btn.setProperty("class", "secondary")
        self.output_btn.setToolTip("Pick explicit destination folder for this batch")
        self.output_btn.clicked.connect(self.pick_output)
        qc_bottom.addWidget(self.output_btn)

        qc_bottom.addStretch()

        self.convert_btn = QPushButton("Convert queue")
        self.convert_btn.setProperty("class", "pill-cta")
        self.convert_btn.clicked.connect(self.start_conversion)
        qc_bottom.addWidget(self.convert_btn)
        qc_layout.addLayout(qc_bottom)

        center_layout.addWidget(self.queue_card)

        # 3. Batch Options Box
        self.opt_box = QGroupBox("Batch Options (Applied when relevant)")
        opt_layout = QHBoxLayout(self.opt_box)
        opt_layout.setContentsMargins(10, 6, 10, 8)

        opt_layout.addWidget(QLabel("PDF OCR Mode:"))
        self.ocr_combo = QComboBox()
        self.ocr_combo.addItem("Auto (detect scanned)", "auto")
        self.ocr_combo.addItem("Native (text only)", "native")
        self.ocr_combo.addItem("Force OCR (all pages)", "force")
        opt_layout.addWidget(self.ocr_combo)

        opt_layout.addSpacing(16)

        opt_layout.addWidget(QLabel("DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 400)
        self.dpi_spin.setValue(150)
        opt_layout.addWidget(self.dpi_spin)

        opt_layout.addSpacing(16)

        opt_layout.addWidget(QLabel("JPEG Quality:"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        opt_layout.addWidget(self.quality_spin)

        opt_layout.addSpacing(16)

        opt_layout.addWidget(QLabel("Pages (PDF):"))
        self.pages_edit = QLineEdit("all")
        self.pages_edit.setPlaceholderText("e.g. all, 1-3, 5")
        self.pages_edit.setMaximumWidth(120)
        opt_layout.addWidget(self.pages_edit)

        opt_layout.addStretch()
        center_layout.addWidget(self.opt_box)

        # 4. Result Action Banner
        self.result_banner = QFrame()
        self.result_banner.setStyleSheet("""
            QFrame {
                background-color: rgba(16, 185, 129, 0.15);
                border: 1px solid #059669;
                border-radius: 8px;
                padding: 4px 10px;
            }
        """)
        rb_layout = QHBoxLayout(self.result_banner)
        rb_layout.setContentsMargins(8, 4, 8, 4)

        self.result_label = QLabel("✔ Conversion completed successfully.")
        self.result_label.setStyleSheet("color: #34d399; font-weight: 600;")
        rb_layout.addWidget(self.result_label, stretch=1)

        self.open_file_btn = QPushButton("Open File")
        self.open_file_btn.setProperty("class", "secondary")
        self.open_file_btn.clicked.connect(self._on_open_last_file)
        rb_layout.addWidget(self.open_file_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setProperty("class", "secondary")
        self.open_folder_btn.clicked.connect(self._on_open_output_folder)
        rb_layout.addWidget(self.open_folder_btn)

        close_rb_btn = QPushButton("✕")
        close_rb_btn.setStyleSheet("background: transparent; color: #94a3b8; font-weight: bold; border: none; padding: 2px 6px;")
        close_rb_btn.clicked.connect(lambda: self.result_banner.setVisible(False))
        rb_layout.addWidget(close_rb_btn)
        self.result_banner.setVisible(False)
        center_layout.addWidget(self.result_banner)

        # 5. Bottom Progress & Cancel
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setValue(0)
        bottom.addWidget(self.bar, stretch=1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_conversion)
        bottom.addWidget(self.cancel_btn)
        center_layout.addLayout(bottom)

        main_layout.addWidget(center_widget, stretch=1)

        # -------------------------------------------------------------------
        # Right Panel: Shortcut Card & History Card (Mockup 1 & 2)
        # -------------------------------------------------------------------
        self.right_panel = QWidget()
        self.right_panel.setFixedWidth(245)
        rp_layout = QVBoxLayout(self.right_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)
        rp_layout.setSpacing(12)

        # Shortcut Card
        self.shortcut_card = QFrame()
        self.shortcut_card.setObjectName("shortcutCard")
        sc_layout = QVBoxLayout(self.shortcut_card)
        sc_layout.setContentsMargins(14, 14, 14, 14)
        sc_layout.setSpacing(8)

        sc_badge = QLabel("Shortcut")
        sc_badge.setStyleSheet("background: rgba(255, 255, 255, 0.22); color: #ffffff; font-weight: 700; font-size: 11px; border-radius: 10px; padding: 3px 8px;")
        sc_badge.setFixedWidth(64)
        sc_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc_layout.addWidget(sc_badge)

        sc_title = QLabel("Radial Menu")
        sc_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #ffffff;")
        sc_layout.addWidget(sc_title)

        sc_desc = QLabel("Hold Shift anywhere to pick a conversion without leaving your work.")
        sc_desc.setStyleSheet("font-size: 12px; color: rgba(255, 255, 255, 0.9); line-height: 1.3;")
        sc_desc.setWordWrap(True)
        sc_layout.addWidget(sc_desc)

        sc_layout.addSpacing(4)
        self.try_radial_btn = QPushButton("Try it now")
        self.try_radial_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #0f172a;
                font-weight: 700;
                border-radius: 18px;
                padding: 7px 16px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
            }
        """)
        self.try_radial_btn.clicked.connect(lambda: self.trigger_radial_menu())
        sc_layout.addWidget(self.try_radial_btn)
        rp_layout.addWidget(self.shortcut_card)

        # History Card
        self.history_card = QFrame()
        self.history_card.setObjectName("historyCard")
        hc_layout = QVBoxLayout(self.history_card)
        hc_layout.setContentsMargins(12, 12, 12, 12)
        hc_layout.setSpacing(6)

        hc_title = QLabel("History")
        hc_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        hc_layout.addWidget(hc_title)

        self.history_container = QWidget()
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(4)
        hc_layout.addWidget(self.history_container)
        hc_layout.addStretch()

        rp_layout.addWidget(self.history_card, stretch=1)
        main_layout.addWidget(self.right_panel)

        self._refresh_history()
        self._refresh_dest_label()

    def _refresh_dest_label(self) -> None:
        """Update the destination indicator according to settings and per-job state."""
        st = get_settings()
        if self.output_dir:
            self.dest_status_lbl.setText(f"Saving to: {self.output_dir.name}")
        elif st.save_to_folder_enabled:
            self.dest_status_lbl.setText(f"Saving to: {st.save_to_folder_path}")
        else:
            self.dest_status_lbl.setText("Saved next to the originals")

    def _refresh_history(self) -> None:
        """Refresh the recent conversion history list in the right panel."""
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = get_settings().history
        if not entries:
            empty_lbl = QLabel("No conversions yet")
            empty_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; padding: 10px 0;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_layout.addWidget(empty_lbl)
            return

        for entry in entries[:5]:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 4, 2, 4)
            row_layout.setSpacing(6)

            route = str(entry.get("route", "")).upper()
            target_ext = route.split("→")[-1].strip() if "→" in route else "DOC"
            badge = QLabel(target_ext[:4])
            badge.setStyleSheet("background-color: #312e81; color: #a5b4fc; font-weight: 700; font-size: 9px; border-radius: 5px; padding: 3px 5px;")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedWidth(34)
            row_layout.addWidget(badge)

            info_layout = QVBoxLayout()
            info_layout.setSpacing(1)
            name_lbl = QLabel(str(entry.get("name", "Converted file")))
            name_lbl.setStyleSheet("font-weight: 600; font-size: 11px;")
            elided = name_lbl.fontMetrics().elidedText(name_lbl.text(), Qt.TextElideMode.ElideMiddle, 130)
            name_lbl.setText(elided)
            info_layout.addWidget(name_lbl)

            sub_lbl = QLabel(f"{entry.get('route', '')} • {entry.get('size', '')}")
            sub_lbl.setStyleSheet("color: #94a3b8; font-size: 10px;")
            info_layout.addWidget(sub_lbl)
            row_layout.addLayout(info_layout, stretch=1)

            p = entry.get("path", "")
            if p:
                open_btn = QPushButton("↗")
                open_btn.setToolTip("Open converted file")
                open_btn.setFixedSize(22, 22)
                open_btn.setStyleSheet("background: transparent; color: #818cf8; border: none; font-size: 13px; font-weight: bold;")
                open_btn.clicked.connect(lambda _, path_str=p: _open_file_externally(Path(path_str)))
                row_layout.addWidget(open_btn)

            self.history_layout.addWidget(row)

    def _refresh_view_state(self) -> None:
        """Update queue count label and destination display."""
        n = len(self.paths)
        if hasattr(self, "queue_count_lbl"):
            self.queue_count_lbl.setText(f"Queue · {n} file{'s' if n != 1 else ''}")
        if hasattr(self, "dest_status_lbl"):
            self._refresh_dest_label()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
                if paths:
                    drop_pos = event.position().toPoint()
                    global_pos = self.mapToGlobal(drop_pos)
                    self.trigger_radial_menu(paths=paths, pos=global_pos)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if not (self._radial_menu and self._radial_menu.isVisible()):
                    paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
                    if paths:
                        drop_pos = event.position().toPoint()
                        global_pos = self.mapToGlobal(drop_pos)
                        self.trigger_radial_menu(paths=paths, pos=global_pos)
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                drop_pos = event.position().toPoint()
                global_pos = self.mapToGlobal(drop_pos)
                self.trigger_radial_menu(paths=paths, pos=global_pos)
            else:
                self.add_paths(paths)
        event.acceptProposedAction()

    def pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add files for conversion",
            "",
            "Supported Files (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif *.ico *.pdf *.docx);;All Files (*.*)",
        )
        if paths:
            self.add_paths([Path(p) for p in paths])

    def pick_output(self) -> None:
        initial = str(self.output_dir) if self.output_dir else str(get_settings().save_to_folder_path)
        chosen = QFileDialog.getExistingDirectory(self, "Select destination folder", initial)
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
            self.result_banner.setVisible(False)
        self._refresh_view_state()

    def remove_selected(self) -> None:
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        for r in selected_rows:
            if 0 <= r < len(self.paths):
                self.paths.pop(r)
                self.table.removeRow(r)
        self._refresh_view_state()

    def clear_queue(self) -> None:
        self.paths.clear()
        self.table.setRowCount(0)
        self.bar.setValue(0)
        self.result_banner.setVisible(False)
        self._refresh_view_state()

    def get_active_or_selected_paths(self) -> list[Path]:
        """Return currently selected files, or all files in queue if none selected."""
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        if selected_rows:
            return [self.paths[r] for r in selected_rows if 0 <= r < len(self.paths)]
        return list(self.paths)

    def trigger_radial_menu(self, paths: Optional[Sequence[Path]] = None, pos: Optional[QPoint] = None) -> None:
        """Open floating circular radial conversion menu near the cursor."""
        target_paths = list(paths) if paths is not None else self.get_active_or_selected_paths()
        if not target_paths and self.paths:
            target_paths = self.paths
        if not target_paths:
            self.pick_files()
            target_paths = self.get_active_or_selected_paths()
        if not target_paths:
            return

        if self._radial_menu and self._radial_menu.isVisible():
            if paths and list(paths) != self._radial_menu.paths:
                self._radial_menu.set_paths(paths)
            return

        menu = RadialConversionMenu(target_paths, parent=self)
        if not menu.available_formats:
            QMessageBox.information(self, "No Routes", "No conversion targets available for selected file(s).")
            return

        def _on_format_selected(fmt: str, pths: list[Path]) -> None:
            self.apply_radial_format(fmt, pths, auto_start=True)
            self._radial_menu = None

        def _on_cancelled() -> None:
            self._radial_menu = None

        menu.format_selected.connect(_on_format_selected)
        menu.cancelled.connect(_on_cancelled)
        self._radial_menu = menu
        menu.show_at_cursor(pos)

    def apply_radial_format(self, target_format: str, paths: list[Path], auto_start: bool = True) -> None:
        """Apply chosen target format from radial menu to queue rows and optionally execute conversion."""
        for p in paths:
            if p not in self.paths:
                self.add_paths([p])
            if p in self.paths:
                idx = self.paths.index(p)
                combo = self.table.cellWidget(idx, 2)
                if combo:
                    item_idx = combo.findData(target_format)
                    if item_idx >= 0:
                        combo.setCurrentIndex(item_idx)

        if auto_start and self.paths:
            self.start_conversion()

    def start_conversion(self) -> None:
        if not self.paths:
            QMessageBox.information(self, "No files", "Add supported files to the queue first.")
            return

        self._last_converted_paths.clear()
        self.result_banner.setVisible(False)

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

            resolved_out = get_settings().resolve_destination(self.output_dir, p.parent)
            jobs.append((i, p, target_fmt, resolved_out, opts))
            self.table.setItem(i, 3, QTableWidgetItem("Waiting…"))

        self.convert_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.radial_btn.setEnabled(False)
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
        if status == "Done" and detail:
            p = Path(detail)
            if p.is_file() and p not in self._last_converted_paths:
                self._last_converted_paths.append(p)
                try:
                    src_p = self.paths[row] if row < len(self.paths) else p
                    combo = self.table.cellWidget(row, 2)
                    target_fmt = combo.currentData() if combo else p.suffix.lstrip(".").lower()
                    route_str = f"{src_p.suffix.lstrip('.').upper()} → {str(target_fmt).upper()}"
                    size_str = _format_size(p.stat().st_size)
                    get_settings().add_history_entry(p.name, route_str, size_str, p)
                    self._refresh_history()
                except Exception as exc:
                    log.debug("History recording error: %s", exc)

    def _on_progress(self, completed: int, total: int) -> None:
        pct = int((completed / total) * 100) if total > 0 else 0
        self.bar.setValue(pct)

    def _on_finished(self, succeeded: int, failed: int, errors: list[str]) -> None:
        self.convert_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.radial_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        total = succeeded + failed
        win = self.window()
        last_out = self._last_converted_paths[0] if self._last_converted_paths else None
        if hasattr(win, "bg_controller") and win.bg_controller:
            if failed == 0:
                win.bg_controller.show_notification(
                    "LocalShift — Conversion Complete",
                    f"Successfully converted {succeeded} file(s). Click to view output.",
                    path=last_out,
                )
            else:
                win.bg_controller.show_notification(
                    "LocalShift — Conversion Completed with Warnings",
                    f"{succeeded}/{total} succeeded, {failed} failed.",
                    path=last_out,
                )

        if failed == 0:
            self.result_label.setText(f"✔ Successfully converted all {succeeded} file(s).")
            self.result_banner.setVisible(True)
            QMessageBox.information(
                self,
                "Conversion Complete",
                f"Successfully converted all {succeeded} file(s).",
            )
        else:
            self.result_label.setText(f"⚠ Completed with issues: {succeeded}/{total} succeeded, {failed} failed.")
            self.result_banner.setVisible(True)
            err_summary = "\n".join(errors[:5])
            if len(errors) > 5:
                err_summary += f"\n… and {len(errors) - 5} more."
            QMessageBox.warning(
                self,
                "Completed with Issues",
                f"Completed: {succeeded}/{total} succeeded.\n{failed} failed.\n\nErrors:\n{err_summary}",
            )

    def _on_open_last_file(self) -> None:
        if self._last_converted_paths:
            _open_file_externally(self._last_converted_paths[-1])

    def _on_open_output_folder(self) -> None:
        if self.output_dir and self.output_dir.is_dir():
            _reveal_in_file_manager(self.output_dir)
        elif self._last_converted_paths:
            _reveal_in_file_manager(self._last_converted_paths[-1].parent)
        elif self.paths:
            _reveal_in_file_manager(self.paths[0].parent)


# ---------------------------------------------------------------------------
# Tab 2: Document Interchange (PDF <-> DOCX)
# ---------------------------------------------------------------------------

class DocxInterchangeTab(QWidget):
    """Dedicated document conversion workflow between PDF and Microsoft Word (DOCX)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.worker: Optional[SingleTaskWorker] = None
        self._last_output_path: Optional[Path] = None
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

        self.open_doc_btn = QPushButton("Open Document")
        self.open_doc_btn.setProperty("class", "secondary")
        self.open_doc_btn.setEnabled(False)
        self.open_doc_btn.clicked.connect(lambda: _open_file_externally(self._last_output_path))
        bottom.addWidget(self.open_doc_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setProperty("class", "secondary")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(lambda: _reveal_in_file_manager(self._last_output_path))
        bottom.addWidget(self.open_folder_btn)

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

        explicit_out = Path(self.dest_edit.text().strip()) if self.dest_edit.text().strip() else None
        out_dir = get_settings().resolve_destination(explicit_out, source.parent)

        options: dict[str, Any] = {}
        if is_pdf_to_docx:
            options["ocr_mode"] = self.ocr_mode_combo.currentData()

        self.convert_btn.setEnabled(False)
        self.open_doc_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
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

        if success and paths:
            self._last_output_path = Path(paths[0])
            self.open_doc_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            QMessageBox.information(self, "Success", msg)
        elif success:
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
        self._last_output_paths: list[Path] = []
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

        self.open_folder_btn = QPushButton("Open Images Folder")
        self.open_folder_btn.setProperty("class", "secondary")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(
            lambda: _reveal_in_file_manager(
                self._last_output_paths[0].parent if self._last_output_paths else None
            )
        )
        bottom.addWidget(self.open_folder_btn)

        self.export_btn = QPushButton("Export Pages")
        self.export_btn.clicked.connect(self.execute_export)
        bottom.addWidget(self.export_btn)
        layout.addLayout(bottom)

    def _on_format_changed(self, index: int = 0) -> None:
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
        explicit_out = Path(self.dest_edit.text().strip()) if self.dest_edit.text().strip() else None
        out_dir = get_settings().resolve_destination(explicit_out, source.parent)

        options: dict[str, Any] = {
            "dpi": dpi,
            "pages": pages,
            "output_pattern": pattern,
        }
        if fmt == "jpeg":
            options["quality"] = quality

        self.export_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
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

        if success and paths:
            self._last_output_paths = [Path(p) for p in paths if Path(p).exists()]
            self.open_folder_btn.setEnabled(bool(self._last_output_paths))
            QMessageBox.information(
                self,
                "Export Complete",
                f"{msg}\nExported {len(paths)} page image(s).",
            )
        elif success:
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
        self._last_output_pdf: Optional[Path] = None
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

        self.open_pdf_btn = QPushButton("Open PDF")
        self.open_pdf_btn.setProperty("class", "secondary")
        self.open_pdf_btn.setEnabled(False)
        self.open_pdf_btn.clicked.connect(lambda: _open_file_externally(getattr(self, "_last_output_pdf", None)))
        bottom.addWidget(self.open_pdf_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setProperty("class", "secondary")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(lambda: _reveal_in_file_manager(getattr(self, "_last_output_pdf", None)))
        bottom.addWidget(self.open_folder_btn)

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
        explicit_out = Path(out_path_str) if out_path_str else None
        if explicit_out is None:
            fallback = self.image_paths[0].parent if self.image_paths else None
            resolved_dir = get_settings().resolve_destination(None, fallback)
            stem = self.image_paths[0].stem if self.image_paths else "assembled"
            out_path = resolved_dir / f"{stem}_assembled.pdf" if resolved_dir else None
        else:
            out_path = explicit_out

        options = {
            "page_size": self.page_size_combo.currentData(),
            "fit": self.fit_combo.currentData(),
            "orientation": self.orient_combo.currentData(),
            "margin": self.margin_spin.value(),
        }

        self.assemble_btn.setEnabled(False)
        self.open_pdf_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
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

        if success and paths:
            self._last_output_pdf = Path(paths[0])
            self.open_pdf_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            QMessageBox.information(self, "Assembly Complete", msg)
        elif success:
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
        self._last_output_path: Optional[Path] = None
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

        self.open_out_btn = QPushButton("Open Result")
        self.open_out_btn.setProperty("class", "secondary")
        self.open_out_btn.setEnabled(False)
        self.open_out_btn.clicked.connect(lambda: _open_file_externally(getattr(self, "_last_output_path", None)))
        bottom.addWidget(self.open_out_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setProperty("class", "secondary")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(lambda: _reveal_in_file_manager(getattr(self, "_last_output_path", None)))
        bottom.addWidget(self.open_folder_btn)

        self.run_btn = QPushButton("Execute Operation")
        self.run_btn.clicked.connect(self.execute_operation)
        bottom.addWidget(self.run_btn)
        layout.addLayout(bottom)

        self._on_op_changed()

    def _on_op_changed(self, index: int = 0) -> None:
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
        explicit_dest = Path(dest_val) if dest_val else None

        if op == "merge":
            if len(self.merge_files) < 2:
                QMessageBox.warning(self, "Not Enough Files", "Please add at least 2 PDF files to merge.")
                return

            fallback = self.merge_files[0].parent
            resolved_dir = get_settings().resolve_destination(None, fallback)
            dest_path = explicit_dest or (resolved_dir / "merged.pdf" if resolved_dir else None)

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

            fallback = src.parent
            resolved_dir = get_settings().resolve_destination(explicit_dest if (explicit_dest and explicit_dest.is_dir()) else None, fallback)

            if op == "split":
                pages = self.split_pages_edit.text().strip() or "all"
                pattern = self.split_pattern_edit.text().strip() or "{stem}_page_{page:02d}.pdf"
                dest_dir = explicit_dest if (explicit_dest and explicit_dest.is_dir()) else resolved_dir

                def _task():
                    return split_pdf(src, output_dir=dest_dir, pages=pages, output_pattern=pattern)

            elif op == "extract":
                pages = self.extract_pages_edit.text().strip()
                if not pages:
                    QMessageBox.warning(self, "Missing Pages", "Please specify pages to extract (e.g. 1-3, 5).")
                    return
                dest_file = explicit_dest if (explicit_dest and not explicit_dest.is_dir()) else (resolved_dir / f"{src.stem}_extract.pdf" if resolved_dir else None)

                def _task():
                    return extract_pdf_pages(src, output_path=dest_file, pages=pages)

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
                dest_file = explicit_dest if (explicit_dest and not explicit_dest.is_dir()) else (resolved_dir / f"{src.stem}_reorder.pdf" if resolved_dir else None)

                def _task():
                    return reorder_pdf_pages(src, page_order=order, output_path=dest_file)

            elif op == "rotate":
                angle = self.rotate_angle_combo.currentData()
                pages = self.rotate_pages_edit.text().strip() or "all"
                relative = self.rotate_relative_check.isChecked()
                dest_file = explicit_dest if (explicit_dest and not explicit_dest.is_dir()) else (resolved_dir / f"{src.stem}_rotated.pdf" if resolved_dir else None)

                def _task():
                    return rotate_pdf_pages(
                        src,
                        rotation=angle,
                        pages=pages,
                        output_path=dest_file,
                        relative=relative,
                    )
            else:
                return

        self.run_btn.setEnabled(False)
        self.open_out_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
        self.bar.setRange(0, 0)

        self.worker = SingleTaskWorker(_task)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def _on_completed(self, success: bool, msg: str, paths: list[str]) -> None:
        self.run_btn.setEnabled(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)

        if success and paths:
            self._last_output_path = Path(paths[0])
            self.open_out_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            QMessageBox.information(self, "Workbench Operation Complete", msg)
        elif success:
            QMessageBox.information(self, "Workbench Operation Complete", msg)
        else:
            QMessageBox.critical(self, "Operation Failed", msg)


# ---------------------------------------------------------------------------
# Settings Dialog (Save to Folder, Appearance, Gestures)
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Centralized persistent settings dialog following the LocalSend design model."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Settings — LocalShift")
        self.setMinimumWidth(560)
        self.settings = get_settings()
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # 1. Save to Folder Section
        save_box = QGroupBox("Save to Folder")
        save_layout = QVBoxLayout(save_box)
        save_layout.setSpacing(10)

        desc = QLabel(
            "Automatically route all converted files, batch jobs, and radial conversions "
            "to a central directory instead of the source file folder."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        save_layout.addWidget(desc)

        self.enable_dest_cb = QCheckBox("Enable custom destination folder")
        self.enable_dest_cb.setChecked(self.settings.save_to_folder_enabled)
        self.enable_dest_cb.toggled.connect(self._on_toggle_dest)
        save_layout.addWidget(self.enable_dest_cb)

        row = QHBoxLayout()
        self.dest_edit = QLineEdit(str(self.settings.save_to_folder_path))
        self.dest_edit.setReadOnly(True)
        row.addWidget(self.dest_edit, stretch=1)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setProperty("class", "secondary")
        self.browse_btn.clicked.connect(self._on_browse_dest)
        row.addWidget(self.browse_btn)

        self.open_btn = QPushButton("Open Folder")
        self.open_btn.setProperty("class", "secondary")
        self.open_btn.clicked.connect(self._on_open_dest)
        row.addWidget(self.open_btn)
        save_layout.addLayout(row)

        self.status_label = QLabel()
        save_layout.addWidget(self.status_label)
        self._refresh_dest_status()
        layout.addWidget(save_box)

        # 2. Appearance Section
        app_box = QGroupBox("Appearance")
        app_layout = QHBoxLayout(app_box)
        app_layout.addWidget(QLabel("Interface Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark Slate (Default)", "dark")
        self.theme_combo.addItem("Light Neutral", "light")
        idx = self.theme_combo.findData(self.settings.theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        app_layout.addWidget(self.theme_combo)
        app_layout.addStretch()
        layout.addWidget(app_box)

        # 3. Radial Menu & Gestures Section
        gesture_box = QGroupBox("Radial Conversion Menu & Gestures")
        gesture_layout = QVBoxLayout(gesture_box)
        self.gesture_cb = QCheckBox("Enable Shift gesture and drag-and-drop activation (in-app & background)")
        self.gesture_cb.setChecked(self.settings.radial_gesture_enabled)
        self.gesture_cb.toggled.connect(self._on_toggle_gesture)
        gesture_layout.addWidget(self.gesture_cb)

        self.startup_cb = QCheckBox("Start LocalShift with Windows (runs quietly in system tray)")
        self.startup_cb.setChecked(is_start_with_windows_enabled())
        self.startup_cb.toggled.connect(self._on_toggle_startup)
        gesture_layout.addWidget(self.startup_cb)

        hint = QLabel(
            "• Hold Shift while dragging files in Windows Explorer or Desktop to summon the wheel.\n"
            "• Release mouse over any format petal to convert instantly into your destination folder.\n"
            "• Tap Shift or press Shift + Space when files are queued in the window.\n"
            "• Use keys 1–9 or Tab/Enter for rapid zero-click conversions."
        )
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        gesture_layout.addWidget(hint)
        layout.addWidget(gesture_box)

        # 4. About Section
        about_box = QGroupBox("About LocalShift")
        about_layout = QVBoxLayout(about_box)
        about_lbl = QLabel(
            "LocalShift v0.14.0 — 100% Offline, Zero Telemetry Windows File Converter.\n"
            "Licensed under the MIT License."
        )
        about_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        about_layout.addWidget(about_lbl)
        layout.addWidget(about_box)

        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        close_btn = QPushButton("Done")
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

    def _refresh_dest_status(self) -> None:
        p = self.settings.save_to_folder_path
        valid, err = validate_destination_directory(p)
        if valid:
            self.status_label.setText("✓ Folder is accessible and writable")
            self.status_label.setStyleSheet("color: #34d399; font-size: 11px;")
        else:
            self.status_label.setText(f"⚠ Inaccessible: {err}")
            self.status_label.setStyleSheet("color: #f87171; font-size: 11px;")

    def _on_toggle_dest(self, checked: bool) -> None:
        self.settings.save_to_folder_enabled = checked
        self._refresh_dest_status()

    def _on_browse_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Save to Folder Destination",
            str(self.settings.save_to_folder_path),
        )
        if folder:
            self.settings.save_to_folder_path = Path(folder)
            self.dest_edit.setText(str(self.settings.save_to_folder_path))
            self._refresh_dest_status()

    def _on_open_dest(self) -> None:
        _reveal_in_file_manager(self.settings.save_to_folder_path)

    def _on_theme_changed(self, index: int = 0) -> None:
        theme = self.theme_combo.currentData()
        self.settings.theme = theme

    def _on_toggle_startup(self, checked: bool) -> None:
        set_start_with_windows_enabled(checked)

    def _on_toggle_gesture(self, checked: bool) -> None:
        self.settings.radial_gesture_enabled = checked
        parent_win = self.parent()
        if hasattr(parent_win, "bg_controller") and parent_win.bg_controller:
            if checked:
                parent_win.bg_controller.start_monitoring()
            else:
                parent_win.bg_controller.stop_monitoring()


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
    """LocalShift main desktop application window with modern sidebar navigation and radial conversion overlay."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalShift — Offline Document & Image Converter")
        self.resize(1020, 680)
        self.setMinimumSize(880, 580)

        self.settings = get_settings()
        self.current_theme = self.settings.theme
        if self.current_theme == "light":
            self.setStyleSheet(LIGHT_THEME_STYLESHEET)
        else:
            self.setStyleSheet(DARK_THEME_STYLESHEET)

        icon_path = _find_app_icon()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -------------------------------------------------------------------
        # Left Sidebar (Mockups 1 & 2)
        # -------------------------------------------------------------------
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(205)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 16)
        sidebar_layout.setSpacing(6)

        # Brand Header
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(10)
        brand_icon = QLabel("✦")
        brand_icon.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #818cf8);
            color: #ffffff;
            font-size: 15px;
            font-weight: bold;
            border-radius: 8px;
            padding: 5px 8px;
        """)
        brand_layout.addWidget(brand_icon)
        brand_title = QLabel("LocalShift")
        brand_title.setObjectName("brandTitle")
        brand_layout.addWidget(brand_title)
        brand_layout.addStretch()
        sidebar_layout.addLayout(brand_layout)
        sidebar_layout.addSpacing(14)

        # Nav Buttons (Mapped to QTabWidget indexes)
        self.nav_buttons: list[QPushButton] = []
        nav_items = [
            ("⇄  Convert files", 0),
            ("📄  PDF ↔ DOCX", 1),
            ("🖼  PDF → Images", 2),
            ("📚  Images → PDF", 3),
            ("☰  PDF Workbench", 4),
            ("🛠  PDF Suite", 5),
        ]
        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setProperty("class", "sidebar-nav")
            btn.clicked.connect(lambda _, i=idx: self.tabs.setCurrentIndex(i))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Bottom System Status Card
        self.bottom_status = QFrame()
        self.bottom_status.setObjectName("bottomStatusCard")
        bs_layout = QVBoxLayout(self.bottom_status)
        bs_layout.setContentsMargins(10, 10, 10, 10)
        bs_layout.setSpacing(4)
        self.status_indicator = QLabel("● Offline engine ready")
        self.status_indicator.setStyleSheet("color: #34d399; font-weight: 700; font-size: 12px;")
        bs_layout.addWidget(self.status_indicator)
        status_desc = QLabel("Zero telemetry. Originals stay untouched.")
        status_desc.setStyleSheet("color: #94a3b8; font-size: 11px; line-height: 1.2;")
        status_desc.setWordWrap(True)
        bs_layout.addWidget(status_desc)
        sidebar_layout.addWidget(self.bottom_status)

        sidebar_layout.addSpacing(6)

        # Settings Button at bottom of sidebar
        self.sidebar_settings_btn = QPushButton("⚙  Settings")
        self.sidebar_settings_btn.setProperty("class", "sidebar-nav")
        self.sidebar_settings_btn.clicked.connect(self.open_settings)
        sidebar_layout.addWidget(self.sidebar_settings_btn)

        layout.addWidget(self.sidebar)

        # -------------------------------------------------------------------
        # Main Area: Top Bar + Workflow Tabs (Mockups 1 & 2)
        # -------------------------------------------------------------------
        main_content = QWidget()
        content_layout = QVBoxLayout(main_content)
        content_layout.setContentsMargins(18, 14, 18, 14)
        content_layout.setSpacing(10)

        # Top Bar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 4)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        self.page_title_lbl = QLabel("Convert files")
        self.page_title_lbl.setStyleSheet("font-size: 20px; font-weight: 800;")
        title_vbox.addWidget(self.page_title_lbl)
        self.page_subtitle_lbl = QLabel("Everything happens on this device.")
        self.page_subtitle_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        title_vbox.addWidget(self.page_subtitle_lbl)
        header_layout.addLayout(title_vbox)

        header_layout.addStretch()

        self.quick_radial_btn = QPushButton("✦ Radial Menu  Shift")
        self.quick_radial_btn.setProperty("class", "pill-cta")
        self.quick_radial_btn.setToolTip("Open circular conversion dial (Press Shift or Shift+Space)")
        self.quick_radial_btn.clicked.connect(self.trigger_radial_menu)
        header_layout.addWidget(self.quick_radial_btn)

        self.theme_btn = QPushButton("☼ Light Mode" if self.current_theme == "dark" else "☾ Dark Mode")
        self.theme_btn.setProperty("class", "secondary")
        self.theme_btn.setToolTip("Toggle dark/light desktop theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.theme_btn)

        content_layout.addLayout(header_layout)

        # Workflow Tabs
        self.tabs = QTabWidget()
        self.convert_tab = FileConverterTab()
        self.docx_tab = DocxInterchangeTab()
        self.rasterize_tab = PdfRasterizeTab()
        self.assembly_tab = ImagesToPdfTab()
        self.workbench_tab = PdfWorkbenchTab()
        self.pdf_suite_tab = PdfToolsSuiteTab()
        self.pdf_suite_tab.tool_triggered.connect(self._on_suite_tool_triggered)

        self.tabs.addTab(self.convert_tab, "File Converter")
        self.tabs.addTab(self.docx_tab, "PDF ↔ DOCX")
        self.tabs.addTab(self.rasterize_tab, "PDF → Images")
        self.tabs.addTab(self.assembly_tab, "Images → PDF")
        self.tabs.addTab(self.workbench_tab, "PDF Workbench")
        self.tabs.addTab(self.pdf_suite_tab, "PDF Suite")
        self.tabs.tabBar().setVisible(False)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        content_layout.addWidget(self.tabs)
        layout.addWidget(main_content, stretch=1)

        self.setCentralWidget(central)
        self.setAcceptDrops(True)

        # In-window Radial Conversion Menu Overlay
        self.radial_overlay = RadialConversionMenu([], parent=self, is_overlay=True)
        self.radial_overlay.hide()
        self.radial_overlay.format_selected.connect(self._on_radial_format_selected)
        self.radial_overlay.cancelled.connect(self.radial_overlay.hide)

        # Install safe app-scoped Shift gesture filter
        self.shift_filter = ShiftActivationFilter(
            main_window=self,
            get_active_files=self._get_active_files_for_radial,
            on_format_selected=self._on_radial_format_selected,
        )
        self.installEventFilter(self.shift_filter)

        # Background Shift+Drag Controller & System Tray
        self.bg_controller = BackgroundGestureController(main_window=self)
        self.bg_controller.conversion_requested.connect(self._on_radial_format_selected)
        if self.settings.radial_gesture_enabled:
            self.bg_controller.start_monitoring()

        self._on_tab_changed(0)

    def _on_suite_tool_triggered(self, tool_id: str) -> None:
        """Handle tool click in PDF Suite tab: switch to workflow or launch execution dialog."""
        if tool_id == "pdf_to_word":
            self.tabs.setCurrentIndex(1)
            self.docx_tab.radio_pdf_to_docx.setChecked(True)
            return
        if tool_id == "word_to_pdf":
            self.tabs.setCurrentIndex(1)
            self.docx_tab.radio_docx_to_pdf.setChecked(True)
            return
        if tool_id == "pdf_to_jpg":
            self.tabs.setCurrentIndex(2)
            self.rasterize_tab.fmt_combo.setCurrentIndex(1)
            return
        if tool_id == "pdf_to_png":
            self.tabs.setCurrentIndex(2)
            self.rasterize_tab.fmt_combo.setCurrentIndex(0)
            return
        if tool_id in ("jpg_to_pdf", "scan_to_pdf"):
            self.tabs.setCurrentIndex(3)
            return
        if tool_id == "merge_pdf":
            self.tabs.setCurrentIndex(4)
            self.workbench_tab.op_combo.setCurrentIndex(0)
            return
        if tool_id == "split_pdf":
            self.tabs.setCurrentIndex(4)
            self.workbench_tab.op_combo.setCurrentIndex(1)
            return
        if tool_id == "extract_pages":
            self.tabs.setCurrentIndex(4)
            self.workbench_tab.op_combo.setCurrentIndex(2)
            return
        if tool_id == "organize_pdf":
            self.tabs.setCurrentIndex(4)
            self.workbench_tab.op_combo.setCurrentIndex(3)
            return
        if tool_id == "rotate_pdf":
            self.tabs.setCurrentIndex(4)
            self.workbench_tab.op_combo.setCurrentIndex(4)
            return

        tool_def = PdfToolRegistry.get_tool(tool_id)
        if tool_def is not None:
            dlg = PdfToolExecutionDialog(tool_def, parent=self)
            dlg.exec()

    def _on_tab_changed(self, index: int) -> None:
        """Synchronize header title, subtitle, and sidebar button highlights."""
        tab_info = [
            ("Convert files", "Everything happens on this device."),
            ("PDF ↔ DOCX", "Fast, high-fidelity bidirectional document interchange."),
            ("PDF → Images", "Rasterize PDF pages into high-resolution PNG or JPEG images."),
            ("Images → PDF", "Assemble multiple photos and graphics into a single PDF document."),
            ("PDF Workbench", "Merge, split, extract, reorder, and rotate PDF documents."),
            ("PDF Suite", "Offline PDF productivity suite with 32 specialized tools."),
        ]
        if 0 <= index < len(tab_info):
            title, subtitle = tab_info[index]
            self.page_title_lbl.setText(title)
            self.page_subtitle_lbl.setText(subtitle)

        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if hasattr(self, "radial_overlay"):
            self.radial_overlay.setGeometry(self.rect())

    def open_settings(self) -> None:
        """Open the persistent settings modal dialog."""
        dlg = SettingsDialog(self)
        dlg.exec()
        if self.settings.theme != self.current_theme:
            self.apply_theme(self.settings.theme)
        self.convert_tab._refresh_dest_label()

    def apply_theme(self, theme: str) -> None:
        """Apply the specified theme ('dark' or 'light')."""
        if theme == "light":
            self.setStyleSheet(LIGHT_THEME_STYLESHEET)
            self.current_theme = "light"
            self.theme_btn.setText("☾ Dark Mode")
        else:
            self.setStyleSheet(DARK_THEME_STYLESHEET)
            self.current_theme = "dark"
            self.theme_btn.setText("☼ Light Mode")

    def toggle_theme(self) -> None:
        """Toggle between modern slate dark theme and crisp neutral light theme."""
        next_theme = "light" if self.current_theme == "dark" else "dark"
        self.settings.theme = next_theme
        self.apply_theme(next_theme)

    def _get_active_files_for_radial(self) -> Sequence[Path]:
        """Collect current files suitable for the radial menu from active tab."""
        if self.tabs.currentWidget() == self.convert_tab:
            return self.convert_tab.get_active_or_selected_paths()
        return []

    def _on_radial_format_selected(self, target_format: str, paths: list[Path]) -> None:
        """Route chosen radial format back to the primary conversion tab and auto-convert."""
        self.tabs.setCurrentWidget(self.convert_tab)
        self.convert_tab.apply_radial_format(target_format, paths, auto_start=True)

    def trigger_radial_menu(self) -> None:
        """Trigger floating radial conversion dial for active queue or picked file."""
        files = self._get_active_files_for_radial()
        if not files and self.convert_tab.paths:
            files = self.convert_tab.paths
        if not files:
            self.convert_tab.pick_files()
            files = self.convert_tab.paths
        if files:
            self.shift_filter.trigger(paths=files)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape and hasattr(self, "radial_overlay") and self.radial_overlay.isVisible():
            self.radial_overlay.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if is_shift_pressed() or (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
                if paths:
                    self.radial_overlay.set_paths(paths)
                    self.radial_overlay.setGeometry(self.rect())
                    self.radial_overlay.show()
                    self.radial_overlay.raise_()
                    self.radial_overlay.track_drag_pos(event.position().toPoint())
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            shift_down = is_shift_pressed() or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if shift_down:
                if not self.radial_overlay.isVisible():
                    paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
                    if paths:
                        self.radial_overlay.set_paths(paths)
                        self.radial_overlay.setGeometry(self.rect())
                        self.radial_overlay.show()
                        self.radial_overlay.raise_()
                if self.radial_overlay.isVisible():
                    self.radial_overlay.track_drag_pos(event.position().toPoint())
            else:
                if self.radial_overlay.isVisible():
                    self.radial_overlay.hide()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        if hasattr(self, "radial_overlay") and self.radial_overlay.isVisible():
            self.radial_overlay.hide()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        if hasattr(self, "radial_overlay") and self.radial_overlay.isVisible():
            pos = event.position().toPoint()
            petal_idx = self.radial_overlay.petal_at_pos(pos)
            target_paths = self.radial_overlay.paths
            self.radial_overlay.hide()
            if 0 <= petal_idx < len(self.radial_overlay.available_formats):
                chosen_fmt = self.radial_overlay.available_formats[petal_idx]
                self._on_radial_format_selected(chosen_fmt, target_paths)
                event.acceptProposedAction()
                return
            else:
                event.acceptProposedAction()
                return

        current_widget = self.tabs.currentWidget()
        if hasattr(current_widget, "dropEvent"):
            current_widget.dropEvent(event)

    def closeEvent(self, event: Any) -> None:
        """Minimize to system tray if background monitoring is active, otherwise exit cleanly."""
        if hasattr(self, "bg_controller") and self.bg_controller and self.bg_controller._tray_icon and self.bg_controller._tray_icon.isVisible():
            event.ignore()
            self.hide()
            self.bg_controller.show_notification(
                "LocalShift is running in background",
                "LocalShift minimized to system tray. Shift+Drag in File Explorer converts files instantly.",
            )
        else:
            if hasattr(self, "bg_controller") and self.bg_controller:
                self.bg_controller.stop_monitoring()
            super().closeEvent(event)


def main() -> None:
    """Launch the LocalShift desktop graphical user interface."""
    app = QApplication(sys.argv)
    win = MainWindow()
    if "--minimized" in sys.argv or "/minimized" in sys.argv:
        # Start minimized to system tray for Windows startup
        pass
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
