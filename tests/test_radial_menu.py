"""
tests/test_radial_menu.py — Unit and integration tests for LocalShift Radial Conversion Menu
and Shift Activation Gesture.

Tests:
1. RadialConversionMenu initialization and target format derivation.
2. Center hub metadata (filename, formatted file size, item count).
3. Multi-file common target intersection.
4. Keyboard navigation (Tab, Arrow keys, 1-9 direct keys, Escape, Enter).
5. Mouse selection and petal hit testing.
6. Screen boundary and DPI clamping in show_at_cursor.
7. ShiftActivationFilter safely ignores text input widgets.
8. ShiftActivationFilter detects Shift trigger gestures.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from PIL import Image

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QSpinBox, QTextEdit, QWidget

from localshift.radial_menu import RadialConversionMenu, ShiftActivationFilter, get_supported_targets


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


_qt_widget_cache: list[object] = []


@pytest.fixture(autouse=True)
def qt_session_cleanup():
    yield
    app = QApplication.instance()
    if app:
        _qt_widget_cache.extend(app.topLevelWidgets())
        app.processEvents()


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    p = tmp_path / "photo.png"
    Image.new("RGB", (100, 100), color="blue").save(p, "PNG")
    return p


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    p = tmp_path / "picture.jpg"
    Image.new("RGB", (100, 100), color="green").save(p, "JPEG")
    return p


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 200)
    p = tmp_path / "report.pdf"
    pdf.save(str(p))
    pdf.close()
    return p


# ---------------------------------------------------------------------------
# Test Target Format Derivation
# ---------------------------------------------------------------------------

class TestTargetFormats:
    def test_single_png_targets(self, sample_png: Path):
        targets = get_supported_targets([sample_png])
        assert len(targets) > 0
        exts = [t.lower() for t in targets]
        assert "webp" in exts
        assert "jpeg" in exts or "jpg" in exts
        assert "pdf" in exts

    def test_single_pdf_targets(self, sample_pdf: Path):
        targets = get_supported_targets([sample_pdf])
        assert len(targets) > 0
        exts = [t.lower() for t in targets]
        assert "png" in exts or "docx" in exts

    def test_multi_image_intersection(self, sample_png: Path, sample_jpeg: Path):
        targets = get_supported_targets([sample_png, sample_jpeg])
        assert len(targets) > 0
        exts = [t.lower() for t in targets]
        assert "pdf" in exts
        assert "webp" in exts

    def test_unsupported_file_empty(self, tmp_path: Path):
        unknown = tmp_path / "test.unknownextxyz"
        unknown.write_text("dummy")
        targets = get_supported_targets([unknown])
        assert targets == []


# ---------------------------------------------------------------------------
# Test RadialConversionMenu
# ---------------------------------------------------------------------------

class TestRadialConversionMenu:
    def test_init_single_file(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        assert menu.paths == [sample_png]
        assert len(menu.target_formats) > 0
        assert menu.selected_index == 0
        assert menu.primary_name == "photo.png"
        assert "KB" in menu.size_str or "B" in menu.size_str
        assert menu.item_count == 1

    def test_init_multi_file(self, qapp, sample_png: Path, sample_jpeg: Path):
        menu = RadialConversionMenu([sample_png, sample_jpeg])
        assert menu.item_count == 2
        assert "2 files" in menu.primary_name
        assert len(menu.target_formats) > 0

    def test_keyboard_navigation_tab_and_arrows(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        num_targets = len(menu.target_formats)
        assert num_targets >= 2

        assert menu.selected_index == 0

        # Press Right Arrow -> index 1
        event_right = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_right)
        assert menu.selected_index == 1

        # Press Down Arrow -> index 2
        event_down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_down)
        assert menu.selected_index == 2 % num_targets

        # Press Left Arrow -> index 1
        event_left = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_left)
        assert menu.selected_index == 1

        # Press Tab -> index 2
        event_tab = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_tab)
        assert menu.selected_index == 2 % num_targets

        # Press Shift+Tab -> index 1
        event_shifttab = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        menu.keyPressEvent(event_shifttab)
        assert menu.selected_index == 1

    def test_number_key_selection(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        selected_fmt = None

        def on_selected(fmt: str, paths: list[Path]):
            nonlocal selected_fmt
            selected_fmt = fmt

        menu.format_selected.connect(on_selected)
        if len(menu.target_formats) >= 3:
            expected = menu.target_formats[2]
            event_3 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_3, Qt.KeyboardModifier.NoModifier, text="3")
            menu.keyPressEvent(event_3)
            assert selected_fmt == expected

    def test_enter_key_confirms_selection(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        selected_format = None

        def on_selected(fmt: str, paths: list[Path]):
            nonlocal selected_format
            selected_format = fmt

        menu.format_selected.connect(on_selected)
        expected_format = menu.target_formats[0]

        event_enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_enter)

        assert selected_format == expected_format

    def test_escape_dismisses_menu(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        cancelled = False

        def on_cancelled():
            nonlocal cancelled
            cancelled = True

        menu.cancelled.connect(on_cancelled)
        event_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(event_esc)

        assert cancelled is True

    def test_show_at_cursor_boundary_clamping(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        screen = qapp.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        # 1. Near bottom right edge
        cursor_near_bottom_right = QPoint(geo.right() + 50, geo.bottom() + 50)
        menu.show_at_cursor(cursor_near_bottom_right)
        rect = menu.geometry()
        assert rect.right() <= geo.right()
        assert rect.bottom() <= geo.bottom()

        # 2. Near top left edge
        cursor_near_top_left = QPoint(geo.left() - 100, geo.top() - 100)
        menu.show_at_cursor(cursor_near_top_left)
        rect = menu.geometry()
        assert rect.left() >= geo.left()
        assert rect.top() >= geo.top()

    def test_accept_drops_enabled(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        assert menu.acceptDrops() is True

    def test_set_paths_updates_targets(self, qapp, sample_png: Path, sample_pdf: Path):
        menu = RadialConversionMenu([sample_png])
        png_targets = set(menu.target_formats)
        assert "webp" in png_targets

        menu.set_paths([sample_pdf])
        pdf_targets = set(menu.target_formats)
        assert "docx" in pdf_targets or "txt" in pdf_targets
        assert menu.paths == [sample_pdf]

    def test_drag_and_drop_on_petal(self, qapp, sample_png: Path):
        from PySide6.QtCore import QMimeData, QPointF, QUrl
        from PySide6.QtGui import QDropEvent

        menu = RadialConversionMenu([sample_png])
        selected_fmt = None
        selected_paths = None

        def on_selected(fmt: str, pths: list[Path]):
            nonlocal selected_fmt, selected_paths
            selected_fmt = fmt
            selected_paths = pths

        menu.format_selected.connect(on_selected)

        # Midpoint of Petal 0
        import math
        count = len(menu.target_formats)
        total_deg = 360.0 / count
        gap_deg = min(4.5, total_deg * 0.15) if count > 1 else 0.0
        start_deg = 90.0 - (gap_deg / 2.0 if count > 1 else 0.0)
        sweep_deg = -(total_deg - gap_deg)
        mid_deg = start_deg + sweep_deg / 2.0
        rad = math.radians(mid_deg)
        drop_pos = QPointF(menu._cx + 100.0 * math.cos(rad), menu._cy - 100.0 * math.sin(rad))

        hit_idx = menu.petal_at_pos(drop_pos)
        assert hit_idx == 0

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(sample_png))])

        drop_event = QDropEvent(
            drop_pos,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        menu.dropEvent(drop_event)

        assert selected_fmt == menu.target_formats[0]
        assert selected_paths == [sample_png]


# ---------------------------------------------------------------------------
# Test ShiftActivationFilter
# ---------------------------------------------------------------------------

class TestShiftActivationFilter:
    def test_ignores_text_inputs(self, qapp):
        filter_obj = ShiftActivationFilter()
        invoked = False

        def on_invoked(pos):
            nonlocal invoked
            invoked = True

        filter_obj.shift_invoked.connect(on_invoked)

        line_edit = QLineEdit()
        text_edit = QTextEdit()
        plain_edit = QPlainTextEdit()
        spin_box = QSpinBox()

        key_press_shift = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
        key_release_shift = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)

        # Event filter on text widgets must return False and NOT emit shift_invoked
        for widget in [line_edit, text_edit, plain_edit, spin_box]:
            res = filter_obj.eventFilter(widget, key_press_shift)
            assert res is False
            res = filter_obj.eventFilter(widget, key_release_shift)
            assert res is False
            assert invoked is False

    def test_shift_space_activation_on_standard_widget(self, qapp):
        filter_obj = ShiftActivationFilter()
        invoked = False

        def on_invoked(pos):
            nonlocal invoked
            invoked = True

        filter_obj.shift_invoked.connect(on_invoked)

        dummy_widget = QWidget()
        key_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier)

        consumed = filter_obj.eventFilter(dummy_widget, key_space)
        assert consumed is True
        assert invoked is True

    def test_overlay_mode_and_drag_tracking(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png], is_overlay=True)
        menu.setGeometry(0, 0, 800, 600)
        qapp.processEvents()
        assert menu.is_overlay is True
        assert menu.width() == 800

        # Center should be at 400, 300
        assert menu._cx == 400.0
        assert menu._cy == 300.0

        # Track drag pos
        hit = menu.track_drag_pos(QPoint(400, 300))
        # Center hub is not a petal, hit should be -1
        assert hit == -1

    def test_escape_key_cancels_menu(self, qapp, sample_png: Path):
        menu = RadialConversionMenu([sample_png])
        cancelled = False

        def on_cancelled():
            nonlocal cancelled
            cancelled = True

        menu.cancelled.connect(on_cancelled)
        esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        menu.keyPressEvent(esc_event)
        assert cancelled is True

    def test_radial_menu_boundary_hysteresis_no_jitter(self, qapp, sample_png: Path):
        """Verify that micro-movements across petal boundaries do not cause alternating jitter."""
        import math
        menu = RadialConversionMenu([sample_png])
        num_targets = len(menu.target_formats)
        assert num_targets >= 2

        step_deg = 360.0 / num_targets
        cx, cy = menu._cx, menu._cy
        r = menu._r_orbit

        # Start inside Petal 0 (12 o'clock = 90 deg in Qt standard coordinates)
        # Petal 0 center is at 0 deg clockwise (90 deg Qt)
        rad0 = math.radians(90.0)
        p0 = QPoint(int(cx + r * math.cos(rad0)), int(cy - r * math.sin(rad0)))
        hit0 = menu.track_drag_pos(p0)
        assert hit0 == 0
        assert menu.hover_index == 0

        # Move incrementally towards the boundary between Petal 0 and Petal 1
        # The nominal boundary is at clockwise angle step_deg / 2.0
        # With hysteresis (e.g. 6 deg), Petal 0 should stay active past nominal boundary
        nominal_boundary_deg = 90.0 - (step_deg / 2.0)
        
        # Test 1 deg past nominal boundary (in boundary deadband)
        deadband_rad = math.radians(nominal_boundary_deg - 1.0)
        pt_deadband = QPoint(int(cx + r * math.cos(deadband_rad)), int(cy - r * math.sin(deadband_rad)))
        hit_deadband = menu.track_drag_pos(pt_deadband)
        # Due to sticky hysteresis, Petal 0 should remain selected!
        assert hit_deadband == 0

        # Now test 10 deg clearly past boundary into Petal 1
        past_rad = math.radians(nominal_boundary_deg - 10.0)
        pt_past = QPoint(int(cx + r * math.cos(past_rad)), int(cy - r * math.sin(past_rad)))
        hit_past = menu.track_drag_pos(pt_past)
        assert hit_past == 1

        # Now move backwards into the deadband: it should stick to Petal 1!
        hit_back_in_deadband = menu.track_drag_pos(pt_deadband)
        assert hit_back_in_deadband == 1

    def test_radial_menu_fast_circular_movement(self, qapp, sample_png: Path):
        """Simulate fast 360-degree sweep across all petals without missed hits or gaps."""
        import math
        menu = RadialConversionMenu([sample_png])
        num_targets = len(menu.target_formats)
        assert num_targets >= 2

        cx, cy = menu._cx, menu._cy
        r = menu._r_orbit

        visited_petals: set[int] = set()
        # Sweep 360 degrees in 120 steps (3 degrees per step)
        for deg in range(0, 360, 3):
            rad = math.radians(deg)
            pos = QPoint(int(cx + r * math.cos(rad)), int(cy - r * math.sin(rad)))
            hit = menu.track_drag_pos(pos)
            if hit >= 0:
                visited_petals.add(hit)

        # All petals must have been smoothly hit without gaps
        assert len(visited_petals) == num_targets

