"""Tests for Windows Shell Integration and Background Gesture Controller."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from localshift.shell_integration import (
    BackgroundGestureController,
    get_explorer_selected_paths,
    is_explorer_or_desktop_foreground,
    is_start_with_windows_enabled,
    set_start_with_windows_enabled,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_start_with_windows_lifecycle():
    """Verify registry query and toggling for autostart."""
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    initial = is_start_with_windows_enabled()
    assert isinstance(initial, bool)

    # Test toggling enable
    success = set_start_with_windows_enabled(True)
    assert success is True
    assert is_start_with_windows_enabled() is True

    # Test toggling disable
    success_disable = set_start_with_windows_enabled(False)
    assert success_disable is True
    assert is_start_with_windows_enabled() is False

    # Restore initial state
    set_start_with_windows_enabled(initial)


def test_explorer_foreground_detection():
    """Verify foreground window class inspection."""
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    res = is_explorer_or_desktop_foreground()
    assert isinstance(res, bool)


def test_get_explorer_selected_paths_returns_paths():
    """Verify IShellWindows querying returns a valid list of Path objects."""
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    paths = get_explorer_selected_paths()
    assert isinstance(paths, list)
    for p in paths:
        assert isinstance(p, Path)


def test_background_gesture_controller_lifecycle(qapp):
    """Verify BackgroundGestureController lifecycle, timers, and signals."""
    controller = BackgroundGestureController(main_window=None)
    assert controller._is_monitoring is False

    controller.start_monitoring()
    assert controller._is_monitoring is True
    assert controller._poll_timer.isActive() is True

    # Notification toast call
    controller.show_notification("Test Title", "Test Message")

    controller.stop_monitoring()
    assert controller._is_monitoring is False
    assert controller._poll_timer.isActive() is False


def test_background_gesture_controller_drag_tracking(qapp, tmp_path):
    """Verify drag tracking updates hover index and release triggers format."""
    f1 = tmp_path / "doc.pdf"
    f1.write_text("dummy")

    controller = BackgroundGestureController(main_window=None)

    # Mock get_explorer_selected_paths to return f1
    with patch("localshift.shell_integration.get_explorer_selected_paths", return_value=[f1]):
        with patch("localshift.shell_integration.is_explorer_or_desktop_foreground", return_value=True):
            controller._trigger_background_radial(QPoint(500, 500))

            assert controller._active_menu is not None
            assert controller._active_menu.paths == [f1]
            assert "docx" in controller._active_menu.available_formats

            # Emit selection through mock signal
            signal_emitted = []
            controller.conversion_requested.connect(lambda fmt, pths: signal_emitted.append((fmt, pths)))

            controller._on_format_selected("docx", [f1])
            assert len(signal_emitted) == 1
            assert signal_emitted[0] == ("docx", [f1])
            assert controller._active_menu is None
            assert controller.state == "CONVERTING"


def test_drag_source_adapters():
    """Verify source adapter classification and path extraction logic."""
    from localshift.shell_integration import (
        DesktopDragSourceAdapter,
        ExplorerDragSourceAdapter,
        FallbackSourceAdapter,
        OleDropSourceAdapter,
    )
    from PySide6.QtCore import QMimeData, QUrl

    # 1. Fallback adapter
    fb = FallbackSourceAdapter()
    assert fb.can_retrieve_paths() is False
    assert fb.get_dragged_paths() == []
    assert fb.name == "Unsupported / Virtual Source"

    # 2. OLE Drop Target adapter with valid file url
    mime = QMimeData()
    p = Path(__file__).resolve()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    ole = OleDropSourceAdapter(mime)
    assert ole.is_source_active() is True
    assert ole.can_retrieve_paths() is True
    paths = ole.get_dragged_paths()
    assert paths == [p]

    # 3. OLE Drop Target without URLs
    empty_mime = QMimeData()
    empty_ole = OleDropSourceAdapter(empty_mime)
    assert empty_ole.is_source_active() is False
    assert empty_ole.get_dragged_paths() == []


def test_gesture_state_machine_transitions(qapp, tmp_path):
    """Verify full state machine transitions and state_changed signals."""
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    states: list[str] = []
    controller.state_changed.connect(states.append)

    assert controller.state == GestureState.IDLE

    # Trigger candidate
    controller._set_state(GestureState.DRAG_CANDIDATE)
    assert controller.state == GestureState.DRAG_CANDIDATE

    f = tmp_path / "test.png"
    f.write_text("x")

    with patch("localshift.shell_integration.get_explorer_selected_paths", return_value=[f]):
        controller._trigger_background_radial(QPoint(100, 100), paths=[f])
        assert controller.state == GestureState.MENU_VISIBLE
        assert controller._active_menu is not None

        # Verify window flags for non-activation and non-stealing focus
        flags = controller._active_menu.windowFlags()
        assert bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        assert controller._active_menu.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Select target
        controller._on_format_selected("jpeg", [f])
        assert controller.state == GestureState.CONVERTING

        # Completed
        controller.on_conversion_completed()
        assert controller.state == GestureState.IDLE

    # Verify history of state transitions
    assert "DRAG_CANDIDATE" in states
    assert "MENU_VISIBLE" in states
    assert "CONVERTING" in states
    assert "COMPLETED" in states
    assert "IDLE" in states


def test_escape_key_cancels_drag_gesture(qapp, tmp_path):
    """Verify VK_ESCAPE instantly cancels active background radial menu."""
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    f = tmp_path / "test.png"
    f.write_text("x")

    with patch("localshift.shell_integration.get_explorer_selected_paths", return_value=[f]):
        controller._trigger_background_radial(QPoint(100, 100), paths=[f])
        assert controller._active_menu is not None
        assert controller.state == GestureState.MENU_VISIBLE

        # Simulate Escape pressed: user32.GetAsyncKeyState(0x1B) & 0x8000
        mock_user32 = MagicMock()
        mock_user32.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 0x1B else 0

        with patch("ctypes.windll.user32", mock_user32, create=True):
            controller._check_gesture_state()
            assert controller._active_menu is None
            assert controller.state == GestureState.IDLE

