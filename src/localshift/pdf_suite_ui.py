"""
localshift.pdf_suite_ui — Searchable PDF task catalog & interactive execution dialog.

Provides:
1. `PdfToolsSuiteTab`: Searchable, category-grouped catalog of local PDF tasks.
   - Real-time search and category filtering.
   - Keyboard-accessible tool choices with concise availability details.
2. `PdfToolExecutionDialog`: Dedicated execution dialog for standalone tools.
   - Drag & Drop file zone with instant path resolution.
   - Context-aware option inputs (page numbers format, watermark opacity, crop margins, password, etc.).
   - Precedence-aware destination resolution (global Save to Folder integration).
   - Responsive background worker thread (QThread) with live progress bar and non-blocking execution.
   - Inline "Open Output File" and "Open Folder" completion actions.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .documents.pdf_tool_registry import (
    ALL_PDF_TOOLS,
    PdfToolDefinition,
    PdfToolRegistry,
    ToolAvailability,
    ToolCategory,
)
from .documents.pdf_tools_engine import (
    add_page_numbers_to_pdf,
    add_watermark_to_pdf,
    compare_two_pdfs,
    compress_pdf_file,
    convert_excel_to_pdf,
    convert_html_to_pdf,
    convert_pdf_to_excel,
    convert_pdf_to_pdfa,
    convert_pdf_to_powerpoint,
    convert_powerpoint_to_pdf,
    crop_pdf_pages,
    delete_pdf_pages,
    edit_pdf_document,
    fill_pdf_forms,
    inspect_pdf_forms,
    ocr_pdf_document,
    pdf_to_markdown_file,
    redact_pdf_document,
    repair_pdf_file,
    sign_pdf_document,
    summarize_pdf_document,
    unlock_pdf_file,
)
from .settings import get_settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background Task Worker for PDF Tools
# ---------------------------------------------------------------------------

class ToolExecutionWorker(QThread):
    """Background worker thread executing PDF tools off the GUI thread."""
    completed = Signal(bool, str, list)  # (success, message, output_paths)

    def __init__(self, task_fn: Callable[[], Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.task_fn = task_fn

    def run(self) -> None:
        try:
            res = self.task_fn()
            if isinstance(res, (list, tuple)):
                paths = [str(p) for p in res]
            elif isinstance(res, (str, Path)):
                paths = [str(res)]
            else:
                paths = []
            self.completed.emit(True, "Tool execution completed successfully.", paths)
        except Exception as exc:
            log.error("Tool execution error: %s", exc, exc_info=True)
            self.completed.emit(False, str(exc), [])


# ---------------------------------------------------------------------------
# Tool Card Widget (Matching User's Mockup Screenshots)
# ---------------------------------------------------------------------------

class ToolCardWidget(QPushButton):
    """Keyboard-accessible PDF tool choice with concise task information."""

    def __init__(self, tool: PdfToolDefinition, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool = tool
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(96)
        self.setObjectName("toolCard")
        self.setAccessibleName(tool.title)
        status = (
            tool.availability.value.replace("_", " ").title()
            if not tool.is_available
            else ""
        )
        self.setAccessibleDescription(
            f"{tool.category.value}. {tool.description}"
            + (f" Status: {status}." if status else "")
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(4)

        title_lbl = QLabel(tool.title)
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(tool.description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setObjectName("mutedText")
        layout.addWidget(desc_lbl)

        if status:
            status_lbl = QLabel(status)
            status_lbl.setObjectName("warningText")
            layout.addWidget(status_lbl)


# ---------------------------------------------------------------------------
# Interactive Tool Execution Dialog
# ---------------------------------------------------------------------------

class PdfToolExecutionDialog(QDialog):
    """Dedicated dialog for configuring and executing any standalone PDF tool."""

    def __init__(self, tool: PdfToolDefinition, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tool = tool
        self.setWindowTitle(f"{tool.title} — LocalShift PDF Suite")
        self.setMinimumWidth(480)
        self.settings = get_settings()
        self.worker: Optional[ToolExecutionWorker] = None
        self._last_output_path: Optional[Path] = None

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(4)
        title_lbl = QLabel(self.tool.title)
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 700;")
        desc_lbl = QLabel(self.tool.description)
        desc_lbl.setObjectName("mutedText")
        desc_lbl.setWordWrap(True)
        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(desc_lbl)
        header.addLayout(title_vbox, stretch=1)
        layout.addLayout(header)

        # 1. Primary Input File Selector
        input_box = QGroupBox("Select Source Document")
        in_layout = QHBoxLayout(input_box)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Choose or drag PDF file here…")
        in_layout.addWidget(self.input_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_input)
        in_layout.addWidget(browse_btn)
        layout.addWidget(input_box)

        # Optional second file selector (for comparison)
        if self.tool.id == "compare_pdf":
            cmp_box = QGroupBox("Second PDF to Compare")
            cmp_layout = QHBoxLayout(cmp_box)
            self.input2_edit = QLineEdit()
            self.input2_edit.setPlaceholderText("Choose second PDF document…")
            cmp_layout.addWidget(self.input2_edit, stretch=1)
            b2 = QPushButton("Browse…")
            b2.clicked.connect(self._on_browse_input2)
            cmp_layout.addWidget(b2)
            layout.addWidget(cmp_box)

        # Setup guide banner for config-required tools
        if self.tool.availability == ToolAvailability.CONFIG_REQUIRED or self.tool.setup_guide:
            setup_box = QGroupBox("Configuration Required")
            setup_box.setObjectName("setupBox")
            setup_layout = QVBoxLayout(setup_box)
            msg = self.tool.setup_guide or self.tool.limitations or "External dependency required."
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            lbl.setObjectName("warningText")
            setup_layout.addWidget(lbl)
            layout.addWidget(setup_box)

        # 2. Dynamic Tool Configuration Options
        self.option_inputs: dict[str, Any] = {}
        if self.tool.id in (
            "page_numbers", "watermark", "crop_pdf", "delete_pages", "compress_pdf",
            "unlock_pdf", "sign_pdf", "edit_pdf", "redact_pdf", "ai_summarizer", "ocr_pdf"
        ):
            opt_box = QGroupBox("Tool Configuration Options")
            opt_layout = QVBoxLayout(opt_box)
            opt_layout.setSpacing(10)

            if self.tool.id == "page_numbers":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Number Format:"))
                fmt_edit = QLineEdit("Page {n} of {total}")
                r1.addWidget(fmt_edit)
                self.option_inputs["format"] = fmt_edit
                opt_layout.addLayout(r1)

                r2 = QHBoxLayout()
                r2.addWidget(QLabel("Position:"))
                pos_combo = QComboBox()
                pos_combo.addItem("Bottom Center", "bottom_center")
                pos_combo.addItem("Bottom Right", "bottom_right")
                pos_combo.addItem("Top Right", "top_right")
                r2.addWidget(pos_combo)
                self.option_inputs["position"] = pos_combo
                opt_layout.addLayout(r2)

            elif self.tool.id == "watermark":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Watermark Text:"))
                txt_edit = QLineEdit("CONFIDENTIAL")
                r1.addWidget(txt_edit)
                self.option_inputs["text"] = txt_edit
                opt_layout.addLayout(r1)

                r2 = QHBoxLayout()
                r2.addWidget(QLabel("Angle (Degrees):"))
                angle_spin = QSpinBox()
                angle_spin.setRange(-90, 90)
                angle_spin.setValue(45)
                r2.addWidget(angle_spin)
                self.option_inputs["angle"] = angle_spin

                r2.addWidget(QLabel("Opacity:"))
                op_spin = QDoubleSpinBox()
                op_spin.setRange(0.05, 1.0)
                op_spin.setSingleStep(0.05)
                op_spin.setValue(0.25)
                r2.addWidget(op_spin)
                self.option_inputs["opacity"] = op_spin
                opt_layout.addLayout(r2)

            elif self.tool.id == "crop_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Margin to Crop (Points):"))
                margin_spin = QDoubleSpinBox()
                margin_spin.setRange(5.0, 200.0)
                margin_spin.setValue(36.0)
                r1.addWidget(margin_spin)
                self.option_inputs["margin_pt"] = margin_spin
                opt_layout.addLayout(r1)

            elif self.tool.id == "delete_pages":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Pages to Delete (e.g. 2, 4):"))
                del_edit = QLineEdit("2")
                r1.addWidget(del_edit)
                self.option_inputs["pages_to_delete"] = del_edit
                opt_layout.addLayout(r1)

            elif self.tool.id == "compress_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Compression Level:"))
                lvl_combo = QComboBox()
                lvl_combo.addItem("Medium (Recommended)", "medium")
                lvl_combo.addItem("High (Maximum Compression)", "high")
                lvl_combo.addItem("Low (Quick)", "low")
                r1.addWidget(lvl_combo)
                self.option_inputs["compression_level"] = lvl_combo
                opt_layout.addLayout(r1)

            elif self.tool.id == "unlock_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Document Password:"))
                pw_edit = QLineEdit()
                pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
                r1.addWidget(pw_edit)
                self.option_inputs["password"] = pw_edit
                opt_layout.addLayout(r1)

            elif self.tool.id == "sign_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Signature / Signer Text:"))
                sig_edit = QLineEdit("Authorized Signer")
                r1.addWidget(sig_edit)
                self.option_inputs["signature_text"] = sig_edit
                opt_layout.addLayout(r1)

                r2 = QHBoxLayout()
                r2.addWidget(QLabel("Position:"))
                pos_combo = QComboBox()
                pos_combo.addItem("Bottom Right", "bottom_right")
                pos_combo.addItem("Bottom Left", "bottom_left")
                pos_combo.addItem("Bottom Center", "bottom_center")
                r2.addWidget(pos_combo)
                self.option_inputs["position"] = pos_combo
                opt_layout.addLayout(r2)

            elif self.tool.id == "edit_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Annotation Action:"))
                act_combo = QComboBox()
                act_combo.addItem("Add Text", "add_text")
                act_combo.addItem("Add Stamp", "add_stamp")
                act_combo.addItem("Highlight", "highlight")
                r1.addWidget(act_combo)
                self.option_inputs["action"] = act_combo

                r1.addWidget(QLabel("Content:"))
                txt_edit = QLineEdit("Approved")
                r1.addWidget(txt_edit)
                self.option_inputs["text"] = txt_edit
                opt_layout.addLayout(r1)

                r2 = QHBoxLayout()
                r2.addWidget(QLabel("Position:"))
                pos_combo = QComboBox()
                pos_combo.addItem("Top Right", "top_right")
                pos_combo.addItem("Top Left", "top_left")
                pos_combo.addItem("Bottom Right", "bottom_right")
                pos_combo.addItem("Bottom Left", "bottom_left")
                pos_combo.addItem("Center", "center")
                r2.addWidget(pos_combo)
                self.option_inputs["position"] = pos_combo
                opt_layout.addLayout(r2)

            elif self.tool.id == "redact_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Text to Permanently Redact:"))
                red_edit = QLineEdit("CONFIDENTIAL")
                r1.addWidget(red_edit)
                self.option_inputs["query"] = red_edit
                opt_layout.addLayout(r1)

            elif self.tool.id == "ai_summarizer":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Key Sentences to Extract:"))
                s_spin = QSpinBox()
                s_spin.setRange(1, 20)
                s_spin.setValue(5)
                r1.addWidget(s_spin)
                self.option_inputs["num_sentences"] = s_spin
                opt_layout.addLayout(r1)

            elif self.tool.id == "ocr_pdf":
                r1 = QHBoxLayout()
                r1.addWidget(QLabel("Output Format:"))
                fmt_combo = QComboBox()
                fmt_combo.addItem("Plain Text (.txt)", "txt")
                fmt_combo.addItem("Word Document (.docx)", "docx")
                r1.addWidget(fmt_combo)
                self.option_inputs["output_format"] = fmt_combo
                opt_layout.addLayout(r1)

            layout.addWidget(opt_box)

        # 3. Output Destination
        dest_box = QGroupBox("Destination Directory")
        dest_layout = QHBoxLayout(dest_box)
        self.dest_edit = QLineEdit()
        self._refresh_dest_path()
        dest_layout.addWidget(self.dest_edit, stretch=1)
        dest_btn = QPushButton("Change…")
        dest_btn.clicked.connect(self._on_browse_dest)
        dest_layout.addWidget(dest_btn)
        layout.addWidget(dest_box)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Action Buttons
        btn_row = QHBoxLayout()
        self.open_file_btn = QPushButton("Open File")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self._on_open_file)
        btn_row.addWidget(self.open_file_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.open_folder_btn)

        btn_row.addStretch()

        self.run_btn = QPushButton(f"Execute {self.tool.title}")
        self.run_btn.setProperty("class", "accent")
        self.run_btn.clicked.connect(self._on_execute)
        btn_row.addWidget(self.run_btn)
        layout.addLayout(btn_row)

    def _refresh_dest_path(self) -> None:
        if self.settings.save_to_folder_enabled:
            self.dest_edit.setText(str(self.settings.save_to_folder_path))
        else:
            self.dest_edit.setText("(Source file folder)")

    def _on_browse_input(self) -> None:
        exts = self.tool.input_extensions or [".pdf"]
        wildcards = " ".join(f"*{ext}" for ext in exts)
        filters = f"{self.tool.title} Inputs ({wildcards});;All Files (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, f"Select input for {self.tool.title}", "", filters)
        if path:
            self.input_edit.setText(path)

    def _on_browse_input2(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select second PDF to compare", "", "PDF Files (*.pdf)")
        if path:
            self.input2_edit.setText(path)

    def _on_browse_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.dest_edit.setText(folder)

    def _on_execute(self) -> None:
        in_path = Path(self.input_edit.text().strip())
        if not in_path.is_file():
            QMessageBox.warning(self, "Missing Input", "Please select a valid input PDF file.")
            return

        dest_val = self.dest_edit.text().strip()
        out_dir = Path(dest_val) if dest_val and dest_val != "(Source file folder)" else None

        self.run_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # Busy spinner

        tool_id = self.tool.id

        def _task():
            if tool_id == "delete_pages":
                pages_str = self.option_inputs["pages_to_delete"].text()
                pages = [int(p.strip()) for p in pages_str.split(",") if p.strip().isdigit()]
                return delete_pdf_pages(in_path, pages_to_delete=pages, output_dir=out_dir)

            elif tool_id == "crop_pdf":
                margin = self.option_inputs["margin_pt"].value()
                return crop_pdf_pages(in_path, margin_pt=margin, output_dir=out_dir)

            elif tool_id == "compress_pdf":
                lvl = self.option_inputs["compression_level"].currentData() or "medium"
                return compress_pdf_file(in_path, compression_level=lvl, output_dir=out_dir)

            elif tool_id == "unlock_pdf":
                pw = self.option_inputs["password"].text()
                return unlock_pdf_file(in_path, password=pw, output_dir=out_dir)

            elif tool_id == "repair_pdf":
                return repair_pdf_file(in_path, output_dir=out_dir)

            elif tool_id == "pdf_to_markdown":
                return pdf_to_markdown_file(in_path, output_dir=out_dir)

            elif tool_id == "page_numbers":
                fmt = self.option_inputs["format"].text()
                pos = self.option_inputs["position"].currentData() or "bottom_center"
                return add_page_numbers_to_pdf(in_path, format_str=fmt, position=pos, output_dir=out_dir)

            elif tool_id == "watermark":
                txt = self.option_inputs["text"].text()
                op = self.option_inputs["opacity"].value()
                ang = self.option_inputs["angle"].value()
                return add_watermark_to_pdf(in_path, text=txt, opacity=op, angle=ang, output_dir=out_dir)

            elif tool_id == "compare_pdf":
                p2 = Path(self.input2_edit.text().strip())
                return compare_two_pdfs(in_path, p2, output_dir=out_dir)

            elif tool_id == "pdf_forms":
                return inspect_pdf_forms(in_path, output_dir=out_dir)

            elif tool_id == "html_to_pdf":
                return convert_html_to_pdf(in_path, output_dir=out_dir)

            elif tool_id == "ocr_pdf":
                fmt = "txt"
                if "output_format" in self.option_inputs:
                    fmt = self.option_inputs["output_format"].currentData() or "txt"
                return ocr_pdf_document(in_path, output_format=fmt, output_dir=out_dir)

            elif tool_id == "pdf_to_excel":
                return convert_pdf_to_excel(in_path, output_dir=out_dir)

            elif tool_id == "pdf_to_powerpoint":
                return convert_pdf_to_powerpoint(in_path, output_dir=out_dir)

            elif tool_id == "pdf_to_pdfa":
                return convert_pdf_to_pdfa(in_path, output_dir=out_dir)

            elif tool_id == "excel_to_pdf":
                return convert_excel_to_pdf(in_path, output_dir=out_dir)

            elif tool_id == "powerpoint_to_pdf":
                return convert_powerpoint_to_pdf(in_path, output_dir=out_dir)

            elif tool_id == "sign_pdf":
                sig_txt = self.option_inputs["signature_text"].text() if "signature_text" in self.option_inputs else ""
                pos = self.option_inputs["position"].currentData() if "position" in self.option_inputs else "bottom_right"
                return sign_pdf_document(in_path, signature_text=sig_txt, position=pos or "bottom_right", output_dir=out_dir)

            elif tool_id == "edit_pdf":
                act = self.option_inputs["action"].currentData() if "action" in self.option_inputs else "add_text"
                txt = self.option_inputs["text"].text() if "text" in self.option_inputs else "Approved"
                pos = self.option_inputs["position"].currentData() if "position" in self.option_inputs else "top_right"
                return edit_pdf_document(in_path, action=act or "add_text", text=txt, position=pos or "top_right", output_dir=out_dir)

            elif tool_id == "redact_pdf":
                query_str = self.option_inputs["query"].text() if "query" in self.option_inputs else "CONFIDENTIAL"
                return redact_pdf_document(in_path, query_or_pattern=query_str, output_dir=out_dir)

            elif tool_id == "ai_summarizer":
                num_s = self.option_inputs["num_sentences"].value() if "num_sentences" in self.option_inputs else 5
                return summarize_pdf_document(in_path, num_sentences=num_s, output_dir=out_dir)

            else:
                if self.tool.availability == ToolAvailability.CONFIG_REQUIRED:
                    guide = self.tool.setup_guide or self.tool.limitations or "External setup required."
                    raise NotImplementedError(f"Tool {tool_id} requires configuration: {guide}")
                raise NotImplementedError(f"Tool {tool_id} is scheduled for subsequent phase.")

        self.worker = ToolExecutionWorker(_task, self)
        self.worker.completed.connect(self._on_task_completed)
        self.worker.start()

    def _on_task_completed(self, success: bool, message: str, paths: list[str]) -> None:
        self.run_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)

        if success and paths:
            self._last_output_path = Path(paths[0])
            self.open_file_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)
            QMessageBox.information(self, "Operation Completed", f"Successfully processed: {self._last_output_path.name}")
        elif success:
            QMessageBox.information(self, "Operation Completed", message)
        else:
            QMessageBox.critical(self, "Tool Failed", message)

    def _on_open_file(self) -> None:
        if self._last_output_path and self._last_output_path.exists():
            import subprocess
            subprocess.Popen(["explorer.exe", str(self._last_output_path)])

    def _on_open_folder(self) -> None:
        if self._last_output_path and self._last_output_path.exists():
            import subprocess
            folder = self._last_output_path.parent
            subprocess.Popen(["explorer.exe", f"/select,{self._last_output_path}"])


# ---------------------------------------------------------------------------
# Searchable PDF Tools Suite Grid Tab
# ---------------------------------------------------------------------------

class PdfToolsSuiteTab(QWidget):
    """Searchable, responsive catalog of local PDF tasks."""
    tool_triggered = Signal(str)  # tool_id for external tab switching

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_category_filter: Optional[ToolCategory] = None
        self._cards: list[ToolCardWidget] = []
        self._visible_tools: list[PdfToolDefinition] = list(ALL_PDF_TOOLS)
        self._column_count = 0

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by task, such as merge or watermark")
        self.search_edit.setAccessibleName("Search PDF tools")
        self.search_edit.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self.search_edit, stretch=1)

        self.category_combo = QComboBox()
        self.category_combo.setAccessibleName("Filter PDF tools by category")
        self.category_combo.addItem("All categories", None)
        for cat in ToolCategory:
            self.category_combo.addItem(cat.value, cat)
        self.category_combo.currentIndexChanged.connect(
            lambda index: self._set_category_filter(self.category_combo.itemData(index))
        )
        filter_row.addWidget(self.category_combo)
        layout.addLayout(filter_row)

        self.result_count = QLabel(f"{len(ALL_PDF_TOOLS)} PDF tools")
        self.result_count.setObjectName("mutedText")
        layout.addWidget(self.result_count)

        self.empty_state = QLabel("No tools match. Try another search or choose All categories.")
        self.empty_state.setObjectName("mutedText")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setVisible(False)
        layout.addWidget(self.empty_state, stretch=1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAccessibleName("PDF tools")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        self.scroll_area.viewport().installEventFilter(self)

        self.grid_container = QWidget()
        self.grid_container.setAutoFillBackground(False)
        self.catalog_layout = QVBoxLayout(self.grid_container)
        self.catalog_layout.setContentsMargins(2, 2, 2, 2)
        self.catalog_layout.setSpacing(12)

        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area, stretch=1)
        self._populate_grid(self._visible_tools)

    def _populate_grid(self, tools: Sequence[PdfToolDefinition]) -> None:
        while self.catalog_layout.count():
            item = self.catalog_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        width = self.scroll_area.viewport().width() if hasattr(self, "scroll_area") else self.width()
        cols = 1 if width < 600 else 2 if width < 900 else 3
        self._column_count = cols
        for category in ToolCategory:
            category_tools = [tool for tool in tools if tool.category == category]
            if not category_tools:
                continue
            heading = QLabel(category.value)
            heading.setObjectName("catalogHeading")
            self.catalog_layout.addWidget(heading)
            grid_widget = QWidget(self.grid_container)
            grid = QGridLayout(grid_widget)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            for index, tool in enumerate(category_tools):
                card = ToolCardWidget(tool, grid_widget)
                card.clicked.connect(
                    lambda checked=False, tool_id=tool.id: self._on_card_clicked(tool_id)
                )
                grid.addWidget(card, index // cols, index % cols)
                self._cards.append(card)
            for column in range(cols):
                grid.setColumnStretch(column, 1)
            self.catalog_layout.addWidget(grid_widget)
        self.catalog_layout.addStretch()

    def _set_category_filter(self, category: Optional[ToolCategory]) -> None:
        self._current_category_filter = category
        self._apply_filters()

    def _on_search_changed(self, text: str) -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        q = self.search_edit.text().strip()
        matched = PdfToolRegistry.search_tools(q)
        if self._current_category_filter is not None:
            matched = [t for t in matched if t.category == self._current_category_filter]
        self._visible_tools = matched
        self.result_count.setText(f"{len(matched)} PDF tool{'s' if len(matched) != 1 else ''}")
        self.empty_state.setVisible(not matched)
        self.scroll_area.setVisible(bool(matched))
        if matched:
            self._populate_grid(matched)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "scroll_area"):
            return
        self._update_grid_columns(self.scroll_area.viewport().width())

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if (
            hasattr(self, "catalog_layout")
            and watched is self.scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._update_grid_columns(event.size().width())
        return super().eventFilter(watched, event)

    def _update_grid_columns(self, width: int) -> None:
        columns = 1 if width < 600 else 2 if width < 900 else 3
        if columns != self._column_count:
            self._populate_grid(self._visible_tools)

    def _on_card_clicked(self, tool_id: str) -> None:
        # Emit signal for main window tab redirection or modal dialog execution
        self.tool_triggered.emit(tool_id)
