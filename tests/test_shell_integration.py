"""Tests for Windows Shell Integration and Background Gesture Controller."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from localshift.shell_integration import (
    BackgroundGestureController,
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


def test_source_startup_uses_importable_module_entrypoint(monkeypatch):
    import localshift.shell_integration as shell_integration

    registry = MagicMock()
    key = MagicMock()
    registry.OpenKey.return_value.__enter__.return_value = key
    registry.HKEY_CURRENT_USER = 1
    registry.KEY_SET_VALUE = 2
    registry.REG_SZ = 3
    monkeypatch.setattr(shell_integration, "winreg", registry)
    monkeypatch.setattr(shell_integration.sys, "platform", "win32")
    monkeypatch.setattr(shell_integration.sys, "executable", r"C:\LocalShift\.venv\Scripts\python.exe")
    monkeypatch.setattr(shell_integration.sys, "frozen", False, raising=False)

    assert set_start_with_windows_enabled(True)

    command = registry.SetValueEx.call_args.args[4]
    assert command == '"C:\\LocalShift\\.venv\\Scripts\\python.exe" -m localshift.gui --minimized'


def test_background_gesture_controller_lifecycle(qapp):
    """Verify BackgroundGestureController lifecycle, timers, and signals."""
    from localshift.settings import get_settings

    settings = get_settings()
    previous_enabled = settings.radial_gesture_enabled
    settings.radial_gesture_enabled = True
    try:
        controller = BackgroundGestureController(main_window=None)
        assert controller._is_monitoring is False

        controller.start_monitoring()
        assert controller._is_monitoring is True
        assert controller._poll_timer.isActive() is True

        controller.show_notification("Test Title", "Test Message")

        controller.stop_monitoring()
        assert controller._is_monitoring is False
        assert controller._poll_timer.isActive() is False
    finally:
        settings.radial_gesture_enabled = previous_enabled


def test_background_monitoring_requires_explicit_enable(qapp):
    from localshift.settings import get_settings

    settings = get_settings()
    previous_enabled = settings.radial_gesture_enabled
    settings.radial_gesture_enabled = False
    controller = BackgroundGestureController(main_window=None)

    controller.start_monitoring()
    assert controller._is_monitoring is False
    assert controller._poll_timer.isActive() is False

    settings.radial_gesture_enabled = previous_enabled


def test_global_gesture_waits_for_actual_ole_drop(qapp):
    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(500, 500))

    assert controller._active_menu is not None
    assert controller._active_menu.awaiting_drop is True
    assert controller._active_menu.paths == []
    assert controller._active_menu.available_formats == []
    assert controller._active_menu.hover_index == -1
    controller.stop_monitoring()


def test_global_ole_drop_dispatches_its_exact_payload(qapp, tmp_path):
    from PIL import Image
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    paths = [tmp_path / "one.png", tmp_path / "two.png"]
    for path in paths:
        Image.new("RGB", (12, 12), "blue").save(path)

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    menu = controller._active_menu
    assert menu is not None
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    results = []
    controller.conversion_requested.connect(lambda fmt, dropped: results.append((fmt, dropped)))

    pos = QPointF(menu._cx, menu._cy - 100)
    event = QDropEvent(pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    menu.dropEvent(event)

    assert len(results) == 1
    assert results[0][0] in menu.available_formats
    assert results[0][1] == paths
    assert controller.state == "CONVERTING"
    assert not controller._drop_timeout.isActive()
    controller.stop_monitoring()


def test_global_dispatch_is_single_use_and_conversion_failure_resets_state(qapp, tmp_path):
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    emitted = []
    states = []
    controller.conversion_requested.connect(lambda *args: emitted.append(args))
    controller.state_changed.connect(states.append)

    controller._on_format_selected("jpeg", [tmp_path / "payload.png"])
    controller._on_format_selected("png", [tmp_path / "stale.png"])

    assert len(emitted) == 1
    assert controller.state == GestureState.CONVERTING

    controller._drag_triggered = True
    controller._lbutton_was_down = True
    controller.on_conversion_failed()

    assert controller.state == GestureState.IDLE
    assert not controller._drag_triggered
    assert not controller._lbutton_was_down
    assert states[-2:] == [GestureState.FAILED.value, GestureState.IDLE.value]
    controller.stop_monitoring()


def test_global_timeout_cleans_up_and_allows_next_gesture(qapp):
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    controller._cancel_unaccepted_drop()

    assert controller._active_menu is None
    assert controller.state == GestureState.IDLE

    controller._trigger_background_radial(QPoint(100, 100))
    assert controller.state == GestureState.MENU_VISIBLE
    controller.stop_monitoring()


def test_global_mouse_release_does_not_select_and_waits_for_drop(qapp):
    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    emitted = []
    controller.conversion_requested.connect(lambda *args: emitted.append(args))
    controller._lbutton_was_down = True
    mock_user32 = MagicMock()
    mock_user32.GetAsyncKeyState.return_value = 0

    with patch("ctypes.windll.user32", mock_user32, create=True), patch(
        "localshift.shell_integration.is_shift_pressed", return_value=False
    ):
        controller._check_gesture_state()

    assert emitted == []
    assert controller._active_menu is not None
    assert controller._drop_timeout.isActive()
    controller.stop_monitoring()


def test_release_while_ole_drag_is_inside_target_waits_for_drop(qapp):
    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    menu = controller._active_menu
    assert menu is not None
    menu._ole_drag_active = True
    controller._lbutton_was_down = True
    mock_user32 = MagicMock()
    mock_user32.GetAsyncKeyState.return_value = 0

    with patch("ctypes.windll.user32", mock_user32, create=True), patch(
        "localshift.shell_integration.is_shift_pressed", return_value=True
    ):
        controller._check_gesture_state()

    assert not controller._drop_timeout.isActive()
    menu.ole_drag_left.emit()
    assert controller._drop_timeout.isActive()
    controller.stop_monitoring()


def test_timeout_does_not_dismiss_active_ole_drag(qapp):
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    menu = controller._active_menu
    assert menu is not None
    menu._ole_drag_active = True

    controller._cancel_unaccepted_drop()

    assert controller._active_menu is menu
    assert controller.state == GestureState.MENU_VISIBLE
    controller.stop_monitoring()


def test_shift_release_cancels_global_gesture(qapp):
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    controller._lbutton_was_down = True
    mock_user32 = MagicMock()
    mock_user32.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 0x01 else 0

    with patch("ctypes.windll.user32", mock_user32, create=True), patch(
        "localshift.shell_integration.is_shift_pressed", return_value=False
    ):
        controller._check_gesture_state()

    assert controller._active_menu is None
    assert controller.state == GestureState.IDLE
    controller.stop_monitoring()


def test_gesture_state_machine_transitions(qapp):
    """Verify full state machine transitions and state_changed signals."""
    from localshift.radial_menu import GestureState

    controller = BackgroundGestureController(main_window=None)
    states: list[str] = []
    controller.state_changed.connect(states.append)

    assert controller.state == GestureState.IDLE

    # Trigger candidate
    controller._set_state(GestureState.DRAG_CANDIDATE)
    assert controller.state == GestureState.DRAG_CANDIDATE

    controller._trigger_background_radial(QPoint(100, 100))
    assert controller.state == GestureState.MENU_VISIBLE
    assert controller._active_menu is not None

    # Verify window flags for non-activation and non-stealing focus.
    flags = controller._active_menu.windowFlags()
    assert bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert controller._active_menu.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    # Verify history of state transitions
    assert "DRAG_CANDIDATE" in states
    assert "MENU_VISIBLE" in states
    assert "CONVERTING" not in states
    controller.stop_monitoring()


def test_escape_key_cancels_drag_gesture(qapp):
    """Verify VK_ESCAPE instantly cancels active background radial menu."""
    from localshift.radial_menu import GestureState

    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    controller = BackgroundGestureController(main_window=None)
    controller._trigger_background_radial(QPoint(100, 100))
    assert controller._active_menu is not None
    assert controller.state == GestureState.MENU_VISIBLE

    # Simulate Escape pressed: VK_ESCAPE = 0x1B.
    mock_user32 = MagicMock()
    mock_user32.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 0x1B else 0

    with patch("ctypes.windll.user32", mock_user32, create=True):
        controller._check_gesture_state()
        assert controller._active_menu is None
        assert controller.state == GestureState.IDLE
    controller.stop_monitoring()
