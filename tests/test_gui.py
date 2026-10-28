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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from localshift.gui import (
    BatchConversionWorker,
    DocxInterchangeTab,
    FileConverterTab,
    ImagesToPdfTab,
    MainWindow,
    PdfRasterizeTab,
    PdfWorkbenchTab,
    SettingsDialog,
    SingleTaskWorker,
)
from localshift.pdf_suite_ui import PdfToolsSuiteTab


@pytest.fixture(scope="session")
def qapp():
    """Shared QApplication instance for GUI tests in offscreen mode."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


_qt_widget_cache: list[object] = []


@pytest.fixture(autouse=True)
def qt_session_cleanup():
    """Keep test widgets referenced until process exit to prevent PySide6 Shiboken premature deletion crash."""
    yield
    app = QApplication.instance()
    if app:
        _qt_widget_cache.extend(app.topLevelWidgets())
        app.processEvents()


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
        assert win.tabs.count() == 6
        tab_names = [win.tabs.tabText(i) for i in range(6)]
        assert "File Converter" in tab_names
        assert "PDF ↔ DOCX" in tab_names
        assert "PDF → Images" in tab_names
        assert "Images → PDF" in tab_names
        assert "PDF Workbench" in tab_names
        assert "PDF Suite" in tab_names

    def test_tab_instances(self, qapp):
        win = MainWindow()
        assert isinstance(win.convert_tab, FileConverterTab)
        assert isinstance(win.docx_tab, DocxInterchangeTab)
        assert isinstance(win.rasterize_tab, PdfRasterizeTab)
        assert isinstance(win.assembly_tab, ImagesToPdfTab)
        assert isinstance(win.workbench_tab, PdfWorkbenchTab)
        assert isinstance(win.pdf_suite_tab, PdfToolsSuiteTab)

    def test_in_window_overlay_does_not_compete_for_ole_target(self, qapp, sample_png, monkeypatch):
        import localshift.gui as gui
        from PySide6.QtCore import QMimeData, QPointF, QUrl

        win = MainWindow()
        win.show()
        qapp.processEvents()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(sample_png))])

        class DragEvent:
            def mimeData(self):
                return mime

            def modifiers(self):
                return Qt.KeyboardModifier.ShiftModifier

            def position(self):
                return QPointF(20, 20)

            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

            def accept(self):
                self.accepted = True

        assert win.acceptDrops()
        assert not win.radial_overlay.acceptDrops()
        original_paths = gui._local_file_paths
        validation_calls = []

        def track_validation(data):
            validation_calls.append(data)
            return original_paths(data)

        monkeypatch.setattr(gui, "_local_file_paths", track_validation)
        event = DragEvent()
        win.dragMoveEvent(event)
        assert event.accepted
        assert not win.radial_overlay.isHidden()
        for _ in range(20):
            win.dragMoveEvent(event)
        qapp.processEvents()
        assert len(validation_calls) == 1

        win.dragLeaveEvent(DragEvent())
        assert win.radial_overlay.isHidden()

        win.dragMoveEvent(event)
        assert not win.radial_overlay.isHidden()
        assert not win.radial_overlay.acceptDrops()
        win._hide_radial_overlay()

    def test_suite_tab_routing(self, qapp):
        win = MainWindow()
        # Verify navigation to existing workflow tab on tool trigger
        win._on_suite_tool_triggered("pdf_to_word")
        assert win.tabs.currentIndex() == 1
        assert win.docx_tab.radio_pdf_to_docx.isChecked()

        win._on_suite_tool_triggered("pdf_to_jpg")
        assert win.tabs.currentIndex() == 2
        assert win.rasterize_tab.fmt_combo.currentIndex() == 1

        win._on_suite_tool_triggered("merge_pdf")
        assert win.tabs.currentIndex() == 4
        assert win.workbench_tab.op_combo.currentIndex() == 0

    def test_global_radial_setting_controls_background_monitoring(self, qapp):
        from localshift.settings import get_settings

        settings = get_settings()
        previous_enabled = settings.radial_gesture_enabled
        settings.radial_gesture_enabled = False
        win = MainWindow()
        dlg = SettingsDialog(win)

        assert win.gesture_status_btn.text() == "Shift+Drag: Off"
        assert dlg.gesture_cb.text() == "Enable global Shift+Drag conversion"
        assert dlg.gesture_status_label.text().endswith("no background gesture monitoring")
        assert not win.bg_controller._is_monitoring

        dlg.gesture_cb.setChecked(True)
        assert win.bg_controller._is_monitoring
        assert dlg.gesture_status_label.text().endswith("external sources are not certified")

        dlg.gesture_cb.setChecked(False)
        assert not win.bg_controller._is_monitoring
        assert not win.bg_controller._poll_timer.isActive()

        win.bg_controller.stop_monitoring()
        settings.radial_gesture_enabled = previous_enabled

    def test_close_with_monitoring_off_exits_even_if_tray_exists(self, qapp):
        from types import SimpleNamespace
        from PySide6.QtGui import QCloseEvent
        from localshift.settings import get_settings

        settings = get_settings()
        previous_enabled = settings.radial_gesture_enabled
        settings.radial_gesture_enabled = False
        win = MainWindow()
        win.bg_controller._is_monitoring = False
        win.bg_controller._tray_icon = SimpleNamespace(isVisible=lambda: True)

        event = QCloseEvent()
        win.closeEvent(event)

        assert event.isAccepted()
        assert not win.bg_controller._is_monitoring
        settings.radial_gesture_enabled = previous_enabled

    @pytest.mark.parametrize(
        ("succeeded", "failed", "terminal_state"),
        [(1, 0, "COMPLETED"), (0, 1, "FAILED")],
    )
    def test_conversion_completion_resets_global_gesture_state(
        self, qapp, dialogs, succeeded, failed, terminal_state
    ):
        from localshift.radial_menu import GestureState
        from localshift.settings import get_settings

        settings = get_settings()
        previous_enabled = settings.radial_gesture_enabled
        settings.radial_gesture_enabled = False
        win = MainWindow()
        states = []
        win.bg_controller.state_changed.connect(states.append)
        win.bg_controller._set_state(GestureState.CONVERTING)

        win.convert_tab._on_finished(succeeded, failed, [])

        assert win.bg_controller.state == GestureState.IDLE
        assert terminal_state in states
        settings.radial_gesture_enabled = previous_enabled


# ---------------------------------------------------------------------------
# Test 2: FileConverterTab
# ---------------------------------------------------------------------------

class TestFileConverterTab:
    def test_primary_workflow_controls_have_accessible_names(self, qapp):
        converter = FileConverterTab()
        rasterizer = PdfRasterizeTab()
        image_assembler = ImagesToPdfTab()
        workbench = PdfWorkbenchTab()
        settings = SettingsDialog()

        assert converter.table.accessibleName() == "Conversion queue"
        assert rasterizer.dpi_spin.accessibleName() == "Resolution in DPI"
        assert rasterizer.dpi_spin.lineEdit().accessibleName() == "Resolution in DPI"
        assert rasterizer.pattern_edit.accessibleName() == "Output naming pattern"
        assert image_assembler.table.accessibleName() == "Images to assemble"
        assert image_assembler.margin_spin.accessibleName() == "Page margin in points"
        assert workbench.merge_table.accessibleName() == "PDF merge order"
        assert settings.settings_tabs.accessibleName() == "Settings pages"
        assert settings.dest_edit.accessibleName() == "Default destination folder"

    def test_compact_queue_fits_narrow_layout(self, qapp, sample_png):
        tab = FileConverterTab()
        tab.resize(540, 480)
        tab.add_paths([sample_png])
        tab.show()
        qapp.processEvents()

        assert tab.table.isColumnHidden(1)
        assert tab.table.isColumnHidden(4)
        assert tab.right_panel.isHidden()
        assert not tab.table.verticalHeader().isVisible()
        combo = tab.table.cellWidget(0, 2)
        assert combo.maximumWidth() <= 170
        assert combo.currentText() == f"{combo.currentData().upper()} (.{combo.currentData()})"
        assert tab.table.horizontalScrollBar().maximum() == 0

        tab.resize(800, 480)
        qapp.processEvents()
        assert not tab.right_panel.isHidden()

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
        bmp_index = combo_png.findData("bmp")
        assert combo_png.itemText(bmp_index) == "BMP (.bmp)"
        assert combo_png.itemData(bmp_index, Qt.ItemDataRole.ToolTipRole) == "BMP image (.bmp)"

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

    def test_queue_sources_are_canonical_paths(self, qapp, sample_png):
        tab = FileConverterTab()
        non_canonical = sample_png.parent / "." / sample_png.name

        tab.add_paths([non_canonical])

        assert tab.paths == [sample_png.resolve()]
        assert tab.paths[0].is_absolute()

    def test_queue_cannot_change_while_batch_is_running(self, qapp, sample_png, monkeypatch):
        tab = FileConverterTab()
        tab.add_paths([sample_png])

        class Signal:
            def connect(self, callback):
                pass

        class RunningWorker:
            def __init__(self, jobs):
                self.item_done = Signal()
                self.progress = Signal()
                self.finished = Signal()

            def isRunning(self):
                return True

            def start(self):
                pass

        monkeypatch.setattr("localshift.gui.BatchConversionWorker", RunningWorker)
        assert tab.start_conversion()
        tab.remove_selected()
        tab.clear_queue()
        tab.add_paths([sample_png])

        assert tab.paths == [sample_png.resolve()]
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
        status_text = tab.backend_status_label.text().casefold()
        assert ("active rendering backend" in status_text) or ("no rendering backend" in status_text)

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

    def test_batch_worker_uses_distinct_real_paths_and_preserves_sources(self, qapp, tmp_path):
        import hashlib
        from PIL import Image

        first_dir, second_dir = tmp_path / "one", tmp_path / "two"
        first_dir.mkdir()
        second_dir.mkdir()
        sources = [first_dir / "résumé.png", second_dir / "résumé.png"]
        Image.new("RGB", (8, 8), "red").save(sources[0])
        Image.new("RGB", (8, 8), "blue").save(sources[1])
        original_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
        done = []
        worker = BatchConversionWorker([(i, path, "jpeg", None, {}) for i, path in enumerate(sources)])
        worker.item_done.connect(lambda *result: done.append(result))

        worker.run()

        assert [status for _, status, _ in done] == ["Done", "Done"]
        assert all(Path(detail).is_file() for _, _, detail in done)
        assert len({Path(detail).parent for _, _, detail in done}) == 2
        assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources] == original_hashes

    def test_batch_worker_snapshots_jobs_and_options(self, qapp, sample_png):
        options = {"quality": 80}
        jobs = [(4, sample_png, "jpeg", None, options)]
        worker = BatchConversionWorker(jobs)
        jobs.clear()
        options["quality"] = 10

        assert len(worker.jobs) == 1
        assert worker.jobs[0][1] == sample_png
        assert worker.jobs[0][4] == {"quality": 80}

    def test_batch_worker_reports_source_removed_after_queueing(self, qapp, tmp_path):
        source = tmp_path / "removed.png"
        source.write_bytes(b"queued but gone")
        source.unlink()
        done = []
        worker = BatchConversionWorker([(0, source, "jpeg", None, {})])
        worker.item_done.connect(lambda *result: done.append(result))

        worker.run()

        assert len(done) == 1
        assert done[0][1] == "Failed"
        assert "Input file not found" in done[0][2]


# ---------------------------------------------------------------------------
# Test 8: End-to-End Workflow Execution Through GUI Layer
# ---------------------------------------------------------------------------

class TestWorkflowExecution:
    def test_repeated_radial_open_reuses_one_menu_and_close_releases_it(self, qapp, sample_png):
        from PySide6.QtCore import QEvent
        from localshift.radial_menu import RadialConversionMenu

        tab = FileConverterTab()
        tab.trigger_radial_menu(paths=[sample_png])
        menu = tab._radial_menu
        assert menu is not None and menu.isVisible()

        tab.trigger_radial_menu(paths=[sample_png])
        assert tab._radial_menu is menu
        assert tab.findChildren(RadialConversionMenu) == [menu]

        menu.close()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()

        assert tab._radial_menu is None
        assert tab.findChildren(RadialConversionMenu) == []

    def test_wheel_cancel_and_reopen_preserves_the_queued_source(self, qapp, sample_png):
        tab = FileConverterTab()
        tab.add_paths([sample_png])
        original_paths = list(tab.paths)

        tab.trigger_radial_menu()
        first_menu = tab._radial_menu
        assert first_menu is not None and first_menu.paths == original_paths
        first_menu._cancel()
        assert tab.paths == original_paths
        assert tab._radial_menu is None

        tab.trigger_radial_menu()
        assert tab._radial_menu is not None
        assert tab._radial_menu.paths == original_paths
        tab._radial_menu._cancel()
        assert tab.paths == original_paths

    def test_missing_source_stays_in_wheel_and_fails_only_its_queue_row(
        self, qapp, tmp_path, monkeypatch
    ):
        import localshift.gui as gui
        from PIL import Image

        source = tmp_path / "selected.png"
        kept_source = tmp_path / "still-present.png"
        Image.new("RGB", (8, 8), "red").save(source)
        Image.new("RGB", (8, 8), "blue").save(kept_source)
        tab = FileConverterTab()
        tab.add_paths([kept_source])
        tab.trigger_radial_menu(paths=[kept_source, source])
        menu = tab._radial_menu
        assert menu is not None
        assert menu.paths == [kept_source.resolve(), source.resolve()]
        source.unlink()
        tab.trigger_radial_menu(paths=[kept_source, source])
        assert tab._radial_menu is menu
        assert menu.paths == [kept_source.resolve(), source.resolve()]

        settings = type(
            "Settings",
            (),
            {
                "save_to_folder_enabled": False,
                "save_to_folder_path": tmp_path,
                "history": [],
                "resolve_destination": lambda self, explicit, fallback: fallback,
            },
        )()
        monkeypatch.setattr(gui, "get_settings", lambda: settings)
        target = "jpeg" if "jpeg" in menu.available_formats else menu.available_formats[0]
        menu.confirm_selection(menu.available_formats.index(target))
        assert tab.worker is not None
        assert tab.worker.wait(5000)
        qapp.processEvents()

        assert tab.paths == [kept_source.resolve(), source.resolve()]
        assert tab.table.item(0, 3).text() == "Done"
        assert tab.table.item(1, 3).text() == "Failed"
        assert "Input file not found" in tab.table.item(1, 4).text()
        assert "restore it or select it again" in tab.table.item(1, 4).text()

    def test_duplicate_basenames_keep_identity_through_wheel_and_conversion(
        self, qapp, tmp_path, monkeypatch
    ):
        import hashlib
        import localshift.gui as gui
        from PIL import Image

        dirs = [tmp_path / "first", tmp_path / "second"]
        for folder in dirs:
            folder.mkdir()
        sources = [folder / "same.png" for folder in dirs]
        Image.new("RGB", (8, 8), "red").save(sources[0])
        Image.new("RGB", (8, 8), "blue").save(sources[1])
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
        tab = FileConverterTab()
        tab.add_paths(sources)
        expected_sources = [path.resolve() for path in sources]
        settings = type("Settings", (), {"resolve_destination": lambda self, explicit, fallback: fallback})()
        monkeypatch.setattr(gui, "get_settings", lambda: settings)

        tab.trigger_radial_menu()
        menu = tab._radial_menu
        assert menu is not None
        assert menu.paths == expected_sources
        menu.confirm_selection(menu.available_formats.index("jpeg"))
        assert tab.worker is not None
        assert tab.worker.wait(5000)
        qapp.processEvents()

        assert tab.paths == expected_sources
        assert [tab.table.item(i, 3).text() for i in range(2)] == ["Done", "Done"]
        outputs = [Path(tab.table.item(i, 4).text()) for i in range(2)]
        assert [path.parent for path in outputs] == dirs
        assert len(set(outputs)) == 2
        assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources] == hashes

    def test_radial_conversion_does_not_replace_running_worker(self, qapp, sample_png, sample_pdf, dialogs):
        tab = FileConverterTab()
        tab.add_paths([sample_pdf])
        tab.worker = type("RunningWorker", (), {"isRunning": lambda self: True})()

        assert not tab.apply_radial_format("jpeg", [sample_png], auto_start=True)
        assert tab.paths == [sample_pdf]
        assert len(dialogs["info"]) == 1

    def test_radial_conversion_only_runs_dropped_paths(self, qapp, sample_png, sample_pdf, monkeypatch):
        tab = FileConverterTab()
        tab.add_paths([sample_pdf])
        captured = {}

        class Signal:
            def connect(self, callback):
                pass

        class CapturingWorker:
            def __init__(self, jobs):
                captured["jobs"] = jobs
                self.item_done = Signal()
                self.progress = Signal()
                self.finished = Signal()

            def start(self):
                pass

        monkeypatch.setattr("localshift.gui.BatchConversionWorker", CapturingWorker)

        assert tab.apply_radial_format("jpeg", [sample_png], auto_start=True)
        assert [job[1] for job in captured["jobs"]] == [sample_png]
        assert captured["jobs"][0][2] == "jpeg"

    def test_file_converter_execution(self, qapp, sample_png, tmp_path, dialogs):
        tab = FileConverterTab()
        tab.add_paths([sample_png])
        tab.output_dir = tmp_path

        combo = tab.table.cellWidget(0, 2)
        jpeg_idx = combo.findData("jpeg")
        combo.setCurrentIndex(jpeg_idx)

        tab.convert_btn.click()
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


class TestPdfToolsCatalog:
    def test_tool_cards_avoid_repeated_category_kickers(self, qapp):
        catalog = PdfToolsSuiteTab()
        card = catalog._cards[0]

        assert card.findChild(QLabel, "toolCategory") is None
        assert card.minimumHeight() == 96

    def test_grid_reflows_when_viewport_crosses_breakpoint(self, qapp):
        catalog = PdfToolsSuiteTab()
        catalog.resize(520, 480)
        catalog.show()
        qapp.processEvents()
        assert catalog.scroll_area.viewport().width() < 600
        assert catalog._column_count == 1

        catalog.resize(900, 480)
        qapp.processEvents()
        assert catalog._column_count == 2

    def test_search_shows_empty_state_and_restores_results(self, qapp):
        catalog = PdfToolsSuiteTab()
        catalog.show()
        catalog.search_edit.setText("no-such-localshift-tool")
        qapp.processEvents()

        assert catalog.empty_state.isVisible()
        assert not catalog.scroll_area.isVisible()
        assert catalog.result_count.text() == "0 PDF tools"

        catalog.search_edit.clear()
        qapp.processEvents()
        assert not catalog.empty_state.isVisible()
        assert catalog.scroll_area.isVisible()
        assert catalog._cards

    def test_tool_choice_is_keyboard_activatable(self, qapp):
        catalog = PdfToolsSuiteTab()
        catalog.show()
        qapp.processEvents()
        triggered = []
        catalog.tool_triggered.connect(triggered.append)
        card = catalog._cards[0]

        assert card.accessibleName() == card.tool.title
        card.setFocus()
        QTest.keyClick(card, Qt.Key.Key_Space)

        assert triggered == [card.tool.id]

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
