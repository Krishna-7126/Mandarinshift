"""
tests/test_gui.py — Automated GUI test suite for LocalShift PySide6 integration.

Tests:
1. Window instantiation and tab structure.
2. Tab 1: File Converter queue, format dropdown, remove, clear, output selection, options mapping.
3. Tab 2: PDF ↔ DOCX interchange, direction toggle, backend discovery status.
4. Tab 3: PDF → Images rasterize options, format toggle, quality enable/disable.
5. Tab 4: Images → PDF multi-image assembly queue, reordering (move up/down), layout options.
6. Tab 5: PDF Workbench operation switching, dynamic UI visibility, validation for Merge, Split, Extract, Reorder, Rotate.
7. Worker thread execution and cancellation.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import pytest
from PIL import Image

# Ensure offscreen Qt platform before importing PySide6
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import PySide6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from localshift.gui import (
    BatchConversionWorker,
    DocxInterchangeTab,
    FileConverterTab,
    ImagesToPdfTab,
    MainWindow,
    PdfRasterizeTab,
    PdfWorkbenchTab,
    SingleTaskWorker,
)


@pytest.fixture(scope="session")
def qapp():
    """Shared QApplication instance for GUI tests in offscreen mode."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Automatically capture and prevent any QMessageBox modal dialogs from blocking tests."""
    from PySide6.QtWidgets import QMessageBox
    captured = {"info": [], "warning": [], "critical": []}
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: (captured["info"].append(args), QMessageBox.StandardButton.Ok)[1],
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        lambda *args, **kwargs: (captured["warning"].append(args), QMessageBox.StandardButton.Ok)[1],
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.critical",
        lambda *args, **kwargs: (captured["critical"].append(args), QMessageBox.StandardButton.Ok)[1],
    )
    return captured


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal 2-page test PDF."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 200)
    pdf.new_page(200, 200)
    path = tmp_path / "sample.pdf"
    pdf.save(str(path))
    pdf.close()
    return path


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """Create a minimal test PNG."""
    path = tmp_path / "sample.png"
    Image.new("RGB", (64, 64), color="blue").save(path, format="PNG")
    return path


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    """Create a minimal test JPEG."""
    path = tmp_path / "sample.jpg"
    Image.new("RGB", (64, 64), color="red").save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# Test 1: MainWindow Structure & Tabs
# ---------------------------------------------------------------------------

class TestMainWindow:
    def test_window_initialization(self, qapp):
        win = MainWindow()
        assert win.windowTitle().startswith("LocalShift")
        assert win.tabs.count() == 5
        tab_names = [win.tabs.tabText(i) for i in range(5)]
        assert "File Converter" in tab_names
        assert "PDF ↔ DOCX" in tab_names
        assert "PDF → Images" in tab_names
        assert "Images → PDF" in tab_names
        assert "PDF Workbench" in tab_names

    def test_tab_instances(self, qapp):
        win = MainWindow()
        assert isinstance(win.convert_tab, FileConverterTab)
        assert isinstance(win.docx_tab, DocxInterchangeTab)
        assert isinstance(win.rasterize_tab, PdfRasterizeTab)
        assert isinstance(win.assembly_tab, ImagesToPdfTab)
        assert isinstance(win.workbench_tab, PdfWorkbenchTab)


# ---------------------------------------------------------------------------
# Test 2: FileConverterTab
# ---------------------------------------------------------------------------

class TestFileConverterTab:
    def test_add_paths_populates_table(self, qapp, sample_png, sample_pdf):
        tab = FileConverterTab()
        tab.add_paths([sample_png, sample_pdf])

        assert len(tab.paths) == 2
        assert tab.table.rowCount() == 2

        # Check Col 0: File Name
        assert tab.table.item(0, 0).text() == "sample.png"
        assert tab.table.item(1, 0).text() == "sample.pdf"

        # Check Col 2: Target format dropdown
        combo_png = tab.table.cellWidget(0, 2)
        assert combo_png.count() > 0
        formats_png = [combo_png.itemData(i) for i in range(combo_png.count())]
        assert "jpeg" in formats_png
        assert "pdf" in formats_png

        combo_pdf = tab.table.cellWidget(1, 2)
        formats_pdf = [combo_pdf.itemData(i) for i in range(combo_pdf.count())]
        assert "docx" in formats_pdf
        assert "png" in formats_pdf

    def test_remove_and_clear_queue(self, qapp, sample_png, sample_pdf):
        tab = FileConverterTab()
        tab.add_paths([sample_png, sample_pdf])
        assert tab.table.rowCount() == 2

        tab.clear_queue()
        assert len(tab.paths) == 0
        assert tab.table.rowCount() == 0

    def test_duplicate_paths_ignored(self, qapp, sample_png):
        tab = FileConverterTab()
        tab.add_paths([sample_png, sample_png])
        assert len(tab.paths) == 1
        assert tab.table.rowCount() == 1

    def test_options_defaults(self, qapp):
        tab = FileConverterTab()
        assert tab.dpi_spin.value() == 150
        assert tab.quality_spin.value() == 85
        assert tab.ocr_combo.currentData() == "auto"
        assert tab.pages_edit.text() == "all"


# ---------------------------------------------------------------------------
# Test 3: DocxInterchangeTab
# ---------------------------------------------------------------------------

class TestDocxInterchangeTab:
    def test_direction_toggle(self, qapp):
        tab = DocxInterchangeTab()
        tab.show()
        assert tab.radio_pdf_to_docx.isChecked()
        assert tab.pdf_settings_widget.isVisible()
        assert not tab.docx_settings_widget.isVisible()

        tab.radio_docx_to_pdf.setChecked(True)
        assert not tab.pdf_settings_widget.isVisible()
        assert tab.docx_settings_widget.isVisible()

    def test_backend_status_display(self, qapp):
        tab = DocxInterchangeTab()
        tab._refresh_backend_status()
        status_text = tab.backend_status_label.text()
        assert ("Active Rendering Backend" in status_text) or ("No rendering backend" in status_text)

    def test_missing_input_validation(self, qapp, monkeypatch):
        tab = DocxInterchangeTab()
        tab.src_edit.setText("")
        warned = []
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args: warned.append(args))
        tab.execute_conversion()
        assert len(warned) == 1
        assert "Missing Input" in warned[0][1]


# ---------------------------------------------------------------------------
# Test 4: PdfRasterizeTab
# ---------------------------------------------------------------------------

class TestPdfRasterizeTab:
    def test_format_switch_toggles_quality(self, qapp):
        tab = PdfRasterizeTab()
        assert tab.fmt_combo.currentData() == "png"
        assert not tab.quality_spin.isEnabled()

        idx = tab.fmt_combo.findData("jpeg")
        tab.fmt_combo.setCurrentIndex(idx)
        assert tab.quality_spin.isEnabled()

    def test_options_defaults(self, qapp):
        tab = PdfRasterizeTab()
        assert tab.dpi_spin.value() == 150
        assert tab.pages_edit.text() == "all"
        assert "{stem}" in tab.pattern_edit.text()
        assert "{page" in tab.pattern_edit.text()


# ---------------------------------------------------------------------------
# Test 5: ImagesToPdfTab
# ---------------------------------------------------------------------------

class TestImagesToPdfTab:
    def test_add_and_reorder_images(self, qapp, sample_png, sample_jpeg):
        tab = ImagesToPdfTab()
        tab.add_images([sample_png, sample_jpeg])

        assert len(tab.image_paths) == 2
        assert tab.table.rowCount() == 2
        assert tab.image_paths[0] == sample_png
        assert tab.image_paths[1] == sample_jpeg

        # Move down first row
        tab.table.setCurrentCell(0, 1)
        tab.move_down()
        assert tab.image_paths[0] == sample_jpeg
        assert tab.image_paths[1] == sample_png

        # Move up second row
        tab.table.setCurrentCell(1, 1)
        tab.move_up()
        assert tab.image_paths[0] == sample_png
        assert tab.image_paths[1] == sample_jpeg

    def test_remove_and_clear(self, qapp, sample_png, sample_jpeg):
        tab = ImagesToPdfTab()
        tab.add_images([sample_png, sample_jpeg])

        tab.table.setCurrentCell(0, 1)
        tab.remove_selected()
        assert len(tab.image_paths) == 1
        assert tab.image_paths[0] == sample_jpeg

        tab.clear_all()
        assert len(tab.image_paths) == 0
        assert tab.table.rowCount() == 0

    def test_layout_options_defaults(self, qapp):
        tab = ImagesToPdfTab()
        assert tab.page_size_combo.currentData() == "original"
        assert tab.fit_combo.currentData() == "contain"
        assert tab.orient_combo.currentData() == "auto"
        assert tab.margin_spin.value() == 0


# ---------------------------------------------------------------------------
# Test 6: PdfWorkbenchTab
# ---------------------------------------------------------------------------

class TestPdfWorkbenchTab:
    def test_operation_switching(self, qapp):
        tab = PdfWorkbenchTab()
        tab.show()

        # Merge
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("merge"))
        assert tab.merge_widget.isVisible()
        assert not tab.single_widget.isVisible()

        # Split
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("split"))
        assert not tab.merge_widget.isVisible()
        assert tab.single_widget.isVisible()
        assert tab.split_box.isVisible()
        assert not tab.extract_box.isVisible()

        # Extract
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("extract"))
        assert tab.extract_box.isVisible()
        assert not tab.split_box.isVisible()

        # Reorder
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("reorder"))
        assert tab.reorder_box.isVisible()

        # Rotate
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("rotate"))
        assert tab.rotate_box.isVisible()

    def test_merge_queue_reordering(self, qapp, tmp_path):
        tab = PdfWorkbenchTab()
        f1 = tmp_path / "doc1.pdf"
        f2 = tmp_path / "doc2.pdf"
        f1.touch()
        f2.touch()

        tab.merge_files = [f1, f2]
        tab._refresh_merge_table()
        assert tab.merge_table.rowCount() == 2

        tab.merge_table.setCurrentCell(0, 1)
        tab.merge_move_down()
        assert tab.merge_files == [f2, f1]

    def test_merge_requires_minimum_two_files(self, qapp, sample_pdf, monkeypatch):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("merge"))
        tab.merge_files = [sample_pdf]
        warned = []
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args: warned.append(args))
        tab.execute_operation()
        assert len(warned) == 1
        assert "Not Enough Files" in warned[0][1]

    def test_extract_validation_missing_pages(self, qapp, sample_pdf, monkeypatch):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("extract"))
        tab.single_input_edit.setText(str(sample_pdf))
        tab.extract_pages_edit.setText("")
        warned = []
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args: warned.append(args))
        tab.execute_operation()
        assert len(warned) == 1
        assert "Missing Pages" in warned[0][1]

    def test_reorder_validation_invalid_integers(self, qapp, sample_pdf, monkeypatch):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("reorder"))
        tab.single_input_edit.setText(str(sample_pdf))
        tab.reorder_edit.setText("abc, xyz")
        warned = []
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *args: warned.append(args))
        tab.execute_operation()
        assert len(warned) == 1
        assert "Invalid Format" in warned[0][1]


# ---------------------------------------------------------------------------
# Test 7: Worker Threads & Cancellation
# ---------------------------------------------------------------------------

class TestWorkers:
    def test_single_task_worker_execution(self, qapp):
        result_holder = []

        def sample_task():
            return Path("output.pdf")

        worker = SingleTaskWorker(sample_task)
        worker.completed.connect(lambda success, msg, paths: result_holder.append((success, msg, paths)))
        worker.run()

        assert len(result_holder) == 1
        assert result_holder[0][0] is True
        assert "output.pdf" in result_holder[0][1]

    def test_single_task_worker_error_handling(self, qapp):
        from localshift.converter import ConversionFailedError
        result_holder = []

        def failing_task():
            raise ConversionFailedError("Simulated failure")

        worker = SingleTaskWorker(failing_task)
        worker.completed.connect(lambda success, msg, paths: result_holder.append((success, msg, paths)))
        worker.run()

        assert len(result_holder) == 1
        assert result_holder[0][0] is False
        assert "Simulated failure" in result_holder[0][1]

    def test_batch_worker_cancellation(self, qapp, sample_png):
        done_items = []
        jobs = [
            (0, sample_png, "jpeg", None, {}),
            (1, sample_png, "jpeg", None, {}),
        ]
        worker = BatchConversionWorker(jobs)
        worker.item_done.connect(lambda idx, status, detail: done_items.append((idx, status)))
        worker.cancel()  # cancel before run
        worker.run()

        assert len(done_items) == 2
        assert all(status == "Cancelled" for _, status in done_items)


# ---------------------------------------------------------------------------
# Test 8: End-to-End Workflow Execution Through GUI Layer
# ---------------------------------------------------------------------------

class TestWorkflowExecution:
    def test_file_converter_execution(self, qapp, sample_png, tmp_path, dialogs):
        tab = FileConverterTab()
        tab.add_paths([sample_png])
        tab.output_dir = tmp_path

        combo = tab.table.cellWidget(0, 2)
        jpeg_idx = combo.findData("jpeg")
        combo.setCurrentIndex(jpeg_idx)

        tab.start_conversion()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert tab.table.item(0, 3).text() == "Done"
        assert len(dialogs["info"]) == 1
        assert "Successfully converted" in dialogs["info"][0][2]

    def test_pdf_rasterize_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfRasterizeTab()
        tab.src_edit.setText(str(sample_pdf))
        tab.dest_edit.setText(str(tmp_path))
        tab.fmt_combo.setCurrentIndex(tab.fmt_combo.findData("png"))

        tab.execute_export()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert "Exported 2 page image(s)" in dialogs["info"][0][2]

    def test_images_to_pdf_assembly_execution(self, qapp, sample_png, sample_jpeg, tmp_path, dialogs):
        tab = ImagesToPdfTab()
        tab.add_images([sample_png, sample_jpeg])
        out_pdf = tmp_path / "assembled.pdf"
        tab.out_edit.setText(str(out_pdf))

        tab.execute_assembly()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert out_pdf.is_file()

    def test_pdf_workbench_merge_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("merge"))
        tab.merge_files = [sample_pdf, sample_pdf]
        out_pdf = tmp_path / "merged.pdf"
        tab.workbench_dest_edit.setText(str(out_pdf))

        tab.execute_operation()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert out_pdf.is_file()

    def test_pdf_workbench_split_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("split"))
        tab.single_input_edit.setText(str(sample_pdf))
        split_dir = tmp_path / "split_output"
        split_dir.mkdir(exist_ok=True)
        tab.workbench_dest_edit.setText(str(split_dir))

        tab.execute_operation()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert len(list(split_dir.glob("*.pdf"))) == 2

    def test_pdf_workbench_extract_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("extract"))
        tab.single_input_edit.setText(str(sample_pdf))
        tab.extract_pages_edit.setText("1")
        out_pdf = tmp_path / "extracted.pdf"
        tab.workbench_dest_edit.setText(str(out_pdf))

        tab.execute_operation()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert out_pdf.is_file()

    def test_pdf_workbench_reorder_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("reorder"))
        tab.single_input_edit.setText(str(sample_pdf))
        tab.reorder_edit.setText("2, 1")
        out_pdf = tmp_path / "reordered.pdf"
        tab.workbench_dest_edit.setText(str(out_pdf))

        tab.execute_operation()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert out_pdf.is_file()

    def test_pdf_workbench_rotate_execution(self, qapp, sample_pdf, tmp_path, dialogs):
        tab = PdfWorkbenchTab()
        tab.op_combo.setCurrentIndex(tab.op_combo.findData("rotate"))
        tab.single_input_edit.setText(str(sample_pdf))
        tab.rotate_angle_combo.setCurrentIndex(tab.rotate_angle_combo.findData(90))
        out_pdf = tmp_path / "rotated.pdf"
        tab.workbench_dest_edit.setText(str(out_pdf))

        tab.execute_operation()
        assert tab.worker is not None
        tab.worker.wait(5000)
        qapp.processEvents()

        assert len(dialogs["info"]) == 1
        assert out_pdf.is_file()

