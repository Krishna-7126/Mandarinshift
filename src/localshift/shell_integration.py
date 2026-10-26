"""
localshift.shell_integration — Windows Shell integration, Explorer selection inspection,
Start with Windows registration, and background Shift+Drag gesture controller.

Features:
1. Active Explorer & Desktop selected items inspection via Shell.Application (IShellWindows).
2. Start with Windows configuration in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
3. Non-invasive BackgroundGestureController detecting Shift+Drag in File Explorer and
   summoning the floating radial conversion menu with direct drop/click execution.
4. Lightweight completion notifications with 'Open File' and 'Open Folder' actions.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import winreg
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QWidget,
)

from .formats import output_formats_for
from .radial_menu import GestureState, RadialConversionMenu, get_supported_targets, is_shift_pressed
from .settings import get_settings

log = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "LocalShift"


# ---------------------------------------------------------------------------
# 1. Start with Windows (Startup Registry) Management
# ---------------------------------------------------------------------------

def is_start_with_windows_enabled() -> bool:
    """Check if LocalShift is configured to launch on Windows startup in HKCU."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_RUN_NAME)
            return bool(val)
    except (FileNotFoundError, OSError):
        return False


def set_start_with_windows_enabled(enable: bool) -> bool:
    """Add or remove LocalShift startup entry in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                if getattr(sys, "frozen", False):
                    exe_path = f'"{sys.executable}" --minimized'
                else:
                    python_exe = sys.executable
                    script = Path(__file__).resolve().parent / "gui.py"
                    exe_path = f'"{python_exe}" "{script}" --minimized'
                winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, exe_path)
                log.info("Registered LocalShift startup entry: %s", exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_RUN_NAME)
                    log.info("Removed LocalShift startup entry.")
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("Could not update Windows startup registry: %s", exc)
        return False


# ---------------------------------------------------------------------------
# 2. Drag Source Adapters & Selection Inspection Architecture
# ---------------------------------------------------------------------------

class DragSourceAdapter:
    """Abstract base adapter for drag-and-drop sources across Windows."""
    name: str = "Base Source"

    def is_source_active(self) -> bool:
        """Return True if this source is currently active/under drag."""
        raise NotImplementedError

    def get_dragged_paths(self) -> list[Path]:
        """Extract filesystem paths for the active drag operation."""
        raise NotImplementedError

    def can_retrieve_paths(self) -> bool:
        """Whether this source supports direct filesystem path resolution."""
        return True


class ExplorerDragSourceAdapter(DragSourceAdapter):
    """Source adapter for Windows File Explorer (CabinetWClass, ExplorerWClass)."""
    name: str = "File Explorer"

    def is_source_active(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                pt = ctypes.wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                hwnd = user32.WindowFromPoint(pt)
            if not hwnd:
                return False
            root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(root or hwnd, buf, 256)
            return buf.value in ("CabinetWClass", "ExplorerWClass")
        except Exception:
            return False

    def get_dragged_paths(self) -> list[Path]:
        return get_explorer_selected_paths()


class DesktopDragSourceAdapter(DragSourceAdapter):
    """Source adapter for Windows Desktop (Progman, WorkerW)."""
    name: str = "Windows Desktop"

    def is_source_active(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                pt = ctypes.wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                hwnd = user32.WindowFromPoint(pt)
            if not hwnd:
                return False
            root = user32.GetAncestor(hwnd, 2)
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(root or hwnd, buf, 256)
            return buf.value in ("Progman", "WorkerW")
        except Exception:
            return False

    def get_dragged_paths(self) -> list[Path]:
        return get_explorer_selected_paths()


class OleDropSourceAdapter(DragSourceAdapter):
    """Source adapter for direct OLE drag payloads dropped into LocalShift UI."""
    name: str = "OLE Drop Target"

    def __init__(self, mime_data: Optional[Any] = None):
        self._mime_data = mime_data

    def is_source_active(self) -> bool:
        return self._mime_data is not None and getattr(self._mime_data, "hasUrls", lambda: False)()

    def get_dragged_paths(self) -> list[Path]:
        if not self.is_source_active():
            return []
        paths: list[Path] = []
        for url in self._mime_data.urls():
            local = url.toLocalFile()
            if local:
                p = Path(local)
                if p.is_file():
                    paths.append(p)
        return paths


class FallbackSourceAdapter(DragSourceAdapter):
    """Fallback source adapter for unsupported or virtual file sources.
    
    Explains limitations for virtual items (e.g. browser images, ZIP archive items)
    which lack filesystem paths without drop extraction.
    """
    name: str = "Unsupported / Virtual Source"

    def is_source_active(self) -> bool:
        return True

    def get_dragged_paths(self) -> list[Path]:
        return []

    def can_retrieve_paths(self) -> bool:
        return False


def detect_active_drag_source() -> DragSourceAdapter:
    """Inspect active desktop state and return matching DragSourceAdapter."""
    explorer = ExplorerDragSourceAdapter()
    if explorer.is_source_active():
        return explorer
    desktop = DesktopDragSourceAdapter()
    if desktop.is_source_active():
        return desktop
    return FallbackSourceAdapter()


def is_explorer_or_desktop_foreground() -> bool:
    """Return True if the active foreground window is Windows File Explorer or Desktop."""
    adapter = detect_active_drag_source()
    return isinstance(adapter, (ExplorerDragSourceAdapter, DesktopDragSourceAdapter))


def get_explorer_selected_paths() -> list[Path]:
    """Retrieve file paths currently selected in active Windows File Explorer or Desktop.

    Queries standard COM Shell.Application (IShellWindows) in a fast, non-blocking call.
    Returns empty list if no files are selected or if Explorer is not active.
    """
    if sys.platform != "win32":
        return []

    ps_cmd = """
    $shell = New-Object -ComObject Shell.Application
    $paths = @()
    foreach ($win in $shell.Windows()) {
        try {
            foreach ($item in $win.Document.SelectedItems()) {
                $p = $item.Path
                if ($p -and (Test-Path -Path $p -PathType Leaf)) {
                    $paths += $p
                }
            }
        } catch {}
    }
    ConvertTo-Json -Compress @($paths | Select-Object -Unique)
    """
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=1.5,
            startupinfo=startupinfo,
        )
        out = res.stdout.strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, str):
            p = Path(data)
            return [p] if p.is_file() else []
        elif isinstance(data, list):
            return [Path(p) for p in data if Path(p).is_file()]
    except Exception as exc:
        log.debug("Could not inspect Explorer selected paths: %s", exc)
    return []


# ---------------------------------------------------------------------------
# 3. Background Gesture Controller (Tangerine-style Background Conversion)
# ---------------------------------------------------------------------------

class BackgroundGestureController(QObject):
    """Monitors desktop state in the background for Shift+Drag conversions.

    Non-invasive architecture:
    - Never installs an invasive global keyboard hook or kernel driver.
    - Discrete state machine: IDLE -> DRAG_CANDIDATE -> MENU_VISIBLE -> TARGET_SELECTED -> CONVERTING -> COMPLETED/FAILED/CANCELLED.
    - Uses non-blocking polling of physical key/mouse button state (VK_LBUTTON, VK_SHIFT, VK_ESCAPE).
    - Uses source-adapter architecture (Explorer, Desktop, OLE).
    - Summons floating RadialConversionMenu centered at cursor without stealing focus or breaking OLE drag capture.
    - Dispatches conversion to the background worker upon format drop/click.
    """

    conversion_requested = Signal(str, list)  # (target_format, list_of_paths)
    state_changed = Signal(str)               # New state name

    def __init__(self, main_window: Optional[QWidget] = None):
        super().__init__(main_window)
        self.main_window = main_window
        self.settings = get_settings()

        self.state: GestureState = GestureState.IDLE
        self._active_menu: Optional[RadialConversionMenu] = None
        self._is_monitoring = False
        self._lbutton_was_down = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_triggered = False

        # 50ms polling timer for responsive, lightweight interaction without high CPU usage
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._check_gesture_state)

        # System tray icon for background operation
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._last_output_path: Optional[Path] = None
        self._init_tray()

    def _set_state(self, new_state: GestureState) -> None:
        if self.state != new_state:
            self.state = new_state
            val = new_state.value if hasattr(new_state, "value") else str(new_state)
            self.state_changed.emit(val)

    def _init_tray(self) -> None:
        """Initialize system tray icon with status, open, and toggle actions."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(self)
        app = QApplication.instance()
        icon = app.windowIcon() if app else QIcon()
        tray.setIcon(icon)
        tray.setToolTip("LocalShift — Offline File Converter")

        menu = QMenu()
        show_action = menu.addAction("✦ Open LocalShift")
        show_action.triggered.connect(self._show_main_window)

        menu.addSeparator()

        gesture_action = menu.addAction("Shift + Drag Conversion Gesture")
        gesture_action.setCheckable(True)
        gesture_action.setChecked(self.settings.radial_gesture_enabled)

        def _toggle_gesture(checked: bool):
            self.settings.radial_gesture_enabled = checked
            if checked:
                self.start_monitoring()
            else:
                self.stop_monitoring()

        gesture_action.toggled.connect(_toggle_gesture)

        startup_action = menu.addAction("Start with Windows")
        startup_action.setCheckable(True)
        startup_action.setChecked(is_start_with_windows_enabled())
        startup_action.toggled.connect(set_start_with_windows_enabled)

        menu.addSeparator()
        quit_action = menu.addAction("Quit LocalShift")
        quit_action.triggered.connect(QApplication.instance().quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.messageClicked.connect(self._on_message_clicked)
        tray.show()
        self._tray_icon = tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_main_window()

    def _on_message_clicked(self) -> None:
        if self._last_output_path and self._last_output_path.exists():
            try:
                if self._last_output_path.is_file():
                    subprocess.Popen(["explorer.exe", f"/select,{self._last_output_path}"])
                else:
                    subprocess.Popen(["explorer.exe", str(self._last_output_path)])
            except Exception as exc:
                log.debug("Could not reveal output path: %s", exc)

    def _show_main_window(self) -> None:
        if self.main_window:
            self.main_window.showNormal()
            self.main_window.activateWindow()
            self.main_window.raise_()

    def start_monitoring(self) -> None:
        """Begin non-invasive background gesture monitoring."""
        if self.settings.radial_gesture_enabled and not self._is_monitoring:
            self._is_monitoring = True
            self._poll_timer.start()
            log.info("Background Shift+Drag gesture controller started.")

    def stop_monitoring(self) -> None:
        """Stop background gesture monitoring."""
        if self._is_monitoring:
            self._is_monitoring = False
            self._poll_timer.stop()
            self._drag_triggered = False
            if self._active_menu and self._active_menu.isVisible():
                self._active_menu.close()
                self._active_menu = None
            self._set_state(GestureState.IDLE)
            log.info("Background Shift+Drag gesture controller stopped.")

    def show_notification(self, title: str, message: str, path: Optional[Path] = None) -> None:
        """Display a system tray completion toast notification."""
        if path:
            self._last_output_path = path
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _check_gesture_state(self) -> None:
        """Evaluate physical mouse button, Shift key, and drag state machine."""
        if sys.platform != "win32":
            return

        import ctypes
        user32 = ctypes.windll.user32

        # 0. Check Escape key for instant cancellation: VK_ESCAPE = 0x1B
        if bool(user32.GetAsyncKeyState(0x1B) & 0x8000):
            if self._active_menu and self._active_menu.isVisible():
                self._active_menu.close()
                self._active_menu = None
            self._set_state(GestureState.CANCELLED)
            self._set_state(GestureState.IDLE)
            self._drag_start_pos = None
            self._drag_triggered = False
            self._lbutton_was_down = False
            return

        # 1. Do not interfere if user is dragging over LocalShift's own active window
        if self.main_window and self.main_window.isActiveWindow() and self.main_window.underMouse():
            return

        # Check physical left mouse button: VK_LBUTTON = 0x01
        lbutton_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        shift_down = is_shift_pressed()
        curr_pos = QCursor.pos()

        # State transition handling
        # A. Mouse button just pressed down
        if lbutton_down and not self._lbutton_was_down:
            self._drag_start_pos = curr_pos
            self._drag_triggered = False
            self._set_state(GestureState.DRAG_CANDIDATE)

        # B. Mouse button held down (drag in progress)
        elif lbutton_down and self._lbutton_was_down:
            if self._active_menu and self._active_menu.isVisible():
                # If user released Shift while dragging, dismiss radial menu so regular drag proceeds
                if not shift_down:
                    self._active_menu.close()
                    self._active_menu = None
                    self._set_state(GestureState.CANCELLED)
                    self._set_state(GestureState.IDLE)
                    return

                local_pos = self._active_menu.mapFromGlobal(curr_pos)
                self._active_menu.track_drag_pos(local_pos)

            elif not self._drag_triggered and self._drag_start_pos:
                dx = curr_pos.x() - self._drag_start_pos.x()
                dy = curr_pos.y() - self._drag_start_pos.y()
                dist_sq = dx * dx + dy * dy

                # Drag threshold: cursor moved more than 8 pixels with button held
                if dist_sq >= 64:
                    if shift_down:
                        source = detect_active_drag_source()
                        if source.can_retrieve_paths():
                            paths = source.get_dragged_paths()
                            if paths:
                                self._trigger_background_radial(curr_pos, paths=paths)

        # C. Mouse button released (drop or release)
        elif not lbutton_down and self._lbutton_was_down:
            if self._active_menu and self._active_menu.isVisible():
                local_pos = self._active_menu.mapFromGlobal(curr_pos)
                hit = self._active_menu.petal_at_pos(local_pos)
                if 0 <= hit < len(self._active_menu.available_formats):
                    self._set_state(GestureState.TARGET_SELECTED)
                    self._active_menu.confirm_selection(hit)
                else:
                    self._active_menu.close()
                    self._active_menu = None
                    self._set_state(GestureState.CANCELLED)
                    self._set_state(GestureState.IDLE)
            else:
                if self.state == GestureState.DRAG_CANDIDATE:
                    self._set_state(GestureState.IDLE)

            self._drag_start_pos = None
            self._drag_triggered = False

        self._lbutton_was_down = lbutton_down

    def _trigger_background_radial(self, pos: QPoint, paths: Optional[list[Path]] = None) -> None:
        """Inspect selected files in Explorer and display the floating radial menu."""
        if self._active_menu and self._active_menu.isVisible():
            return

        selected_paths = paths if paths is not None else get_explorer_selected_paths()
        if not selected_paths:
            return

        available_targets = get_supported_targets(selected_paths)
        if not available_targets:
            return

        self._drag_triggered = True

        menu = RadialConversionMenu(selected_paths, parent=None, is_overlay=False)
        menu.format_selected.connect(self._on_format_selected)
        menu.cancelled.connect(self._on_menu_cancelled)
        self._active_menu = menu
        self._set_state(GestureState.MENU_VISIBLE)
        menu.show_at_cursor(pos)

    def _on_format_selected(self, target_format: str, paths: list[Path]) -> None:
        self._active_menu = None
        self._set_state(GestureState.CONVERTING)
        self.conversion_requested.emit(target_format, paths)

    def _on_menu_cancelled(self) -> None:
        self._active_menu = None
        self._set_state(GestureState.CANCELLED)
        self._set_state(GestureState.IDLE)

    def on_conversion_completed(self) -> None:
        """Notify state machine that conversion finished successfully."""
        self._set_state(GestureState.COMPLETED)
        self._set_state(GestureState.IDLE)

    def on_conversion_failed(self) -> None:
        """Notify state machine that conversion failed."""
        self._set_state(GestureState.FAILED)
        self._set_state(GestureState.IDLE)

