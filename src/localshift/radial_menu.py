"""
localshift.radial_menu — Shift-activated radial conversion menu for LocalShift.

Provides a floating, modern circular conversion dial inspired by radial desktop
workflows. Appears near the cursor when invoked via Shift gestures, drag-and-drop,
or toolbar shortcuts.

Key features:
- Center hub: Shows thumbnail/icon, filename, file size badge, and item count.
- Radial segments (petals): Dynamically arranged for supported target formats.
- Interactive feedback: Smooth outward offset on hover, rich highlight contrast,
  and keyboard navigation (Tab/Arrows/Enter/Esc/1-9).
- Screen-edge and multi-monitor safe: Clamps position to keep entire widget on-screen.
- App-scoped event filter: Safe activation without global Windows hooks or text input interception.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QCloseEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from .formats import FORMAT_LABELS, input_format, output_formats_for
from .planner import MAX_INPUT_BYTES
from .settings import get_settings

log = logging.getLogger(__name__)


def is_shift_pressed() -> bool:
    """Check physical Shift key state across Windows desktop sessions.

    Uses Win32 GetAsyncKeyState(VK_SHIFT = 0x10) when available without installing
    any global hooks. Falls back to Qt keyboardModifiers() if Win32 API is unavailable.
    """
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
    except Exception:
        pass
    app = QGuiApplication.instance()
    if app:
        return bool(app.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
    return False


from enum import Enum


class GestureState(str, Enum):
    """Explicit state machine stages for the Shift+Drag conversion lifecycle."""
    IDLE = "IDLE"
    DRAG_CANDIDATE = "DRAG_CANDIDATE"
    MENU_VISIBLE = "MENU_VISIBLE"
    TARGET_SELECTED = "TARGET_SELECTED"
    CONVERTING = "CONVERTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    # Backwards-compatibility aliases
    DRAG_ENTERED = "DRAG_CANDIDATE"
    SHIFT_ARMED = "DRAG_CANDIDATE"
    RADIAL_ACTIVE = "MENU_VISIBLE"
    PETAL_HOVER = "MENU_VISIBLE"
    DROP_ACCEPTED = "TARGET_SELECTED"



def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024.0
    return f"{mb:.1f} MB"


def _clamped_menu_origin(cursor_pos: QPoint, screen_rect: QRect, size: QSize) -> QPoint:
    """Keep the menu visible while ensuring its activation pointer remains in its hit area."""
    def axis_origin(cursor: int, start: int, extent: int, menu_extent: int) -> int:
        if extent <= menu_extent:
            return start
        low = start + 10
        high = start + extent - menu_extent - 10
        origin = min(max(cursor - menu_extent // 2, low), high)
        if cursor < origin:
            return cursor
        if cursor >= origin + menu_extent:
            return cursor - menu_extent + 1
        return origin

    return QPoint(
        axis_origin(cursor_pos.x(), screen_rect.left(), screen_rect.width(), size.width()),
        axis_origin(cursor_pos.y(), screen_rect.top(), screen_rect.height(), size.height()),
    )


def get_supported_targets(paths: Sequence[Path]) -> list[str]:
    """Derive genuinely supported target formats for given paths from registry."""
    valid_paths = [p for p in paths if p.is_file()]
    if not valid_paths:
        return []
    if len(valid_paths) == 1:
        return output_formats_for(valid_paths[0])
    common_targets: Optional[set[str]] = None
    for p in valid_paths:
        targets = set(output_formats_for(p))
        if common_targets is None:
            common_targets = targets
        else:
            common_targets.intersection_update(targets)
    if common_targets:
        return sorted(common_targets)
    return []


def _create_petal_path(
    cx: float,
    cy: float,
    r_inner: float,
    r_outer: float,
    start_deg: float,
    sweep_deg: float,
    offset_px: float = 0.0,
) -> QPainterPath:
    """Construct an annular sector (petal) with optional outward radial offset.

    Angles are in Qt degrees (positive = counter-clockwise, 90 = 12 o'clock).
    """
    mid_deg = start_deg + sweep_deg / 2.0
    mid_rad = math.radians(mid_deg)
    # Qt y-axis points down, so positive counter-clockwise rotation moves up (-sin)
    ox = cx + offset_px * math.cos(mid_rad)
    oy = cy - offset_px * math.sin(mid_rad)

    ro = QRectF(ox - r_outer, oy - r_outer, 2.0 * r_outer, 2.0 * r_outer)
    ri = QRectF(ox - r_inner, oy - r_inner, 2.0 * r_inner, 2.0 * r_inner)

    path = QPainterPath()
    path.arcMoveTo(ro, start_deg)
    path.arcTo(ro, start_deg, sweep_deg)
    path.arcTo(ri, start_deg + sweep_deg, -sweep_deg)
    path.closeSubpath()
    return path


class RadialConversionMenu(QWidget):
    """Radial conversion menu overlay.

    Displays available target formats in circular segments around a central file hub.
    Supports in-window overlay and standalone popup modes, mouse hover/click,
    direct OLE drag & drop, keyboard navigation, and automatic screen boundary clamping.
    """

    format_selected = Signal(str, list)  # (target_format, list_of_paths)
    cancelled = Signal()
    ole_drag_left = Signal()

    def __init__(
        self,
        paths: Sequence[Path],
        parent: Optional[QWidget] = None,
        output_dir: Optional[Path] = None,
        is_overlay: bool = False,
        awaiting_drop: bool = False,
    ):
        super().__init__(parent)
        self.paths: list[Path] = [p for p in paths if p.is_file()]
        self.output_dir = output_dir
        self.is_overlay = is_overlay
        self.awaiting_drop = awaiting_drop
        self._drop_message: Optional[str] = None
        self._ole_drag_active = False
        self._selection_confirmed = False
        self._cancelled = False

        # Geometry dimensions
        self._wheel_size = 400
        self.resize(self._wheel_size, self._wheel_size + 60)
        self._cx = self.width() / 2.0
        self._cy = self.height() / 2.0
        self._r_inner = 58.0
        self._r_outer = 138.0
        self._r_orbit = 104.0
        self._r_petal = 40.0

        # State
        self._available_formats: list[str] = self._determine_formats()
        self._hover_index: int = 0 if self._available_formats and not awaiting_drop else -1
        self._thumbnail_pixmap: Optional[QPixmap] = self._generate_thumbnail()

        theme_owner = parent.window() if parent else None
        self.set_theme(getattr(theme_owner, "current_theme", get_settings().theme))

        if not is_overlay:
            # Window properties for standalone floating mode (does not steal focus or drop drag capture)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if is_overlay else Qt.FocusPolicy.NoFocus)
        self.setAcceptDrops(True)

    def set_theme(self, theme: str) -> None:
        light = theme == "light"
        self._c_bg = QColor(250, 248, 242, 248) if light else QColor(27, 29, 27, 248)
        self._c_card = QColor(255, 253, 247) if light else QColor(37, 40, 36)
        self._c_hover = QColor(234, 216, 208) if light else QColor(89, 55, 45)
        self._c_border = QColor(174, 170, 160, 220) if light else QColor(83, 86, 78, 230)
        self._c_border_hover = QColor(143, 63, 46) if light else QColor(228, 154, 130)
        self._c_text_white = QColor(39, 40, 37) if light else QColor(243, 241, 232)
        self._c_text_muted = QColor(84, 86, 80) if light else QColor(194, 193, 184)
        self._c_text_accent = QColor(135, 57, 41) if light else QColor(240, 173, 151)
        self._c_overlay = QColor(32, 31, 27, 150) if light else QColor(10, 12, 10, 224)
        self._c_hub = QColor(251, 249, 243) if light else QColor(29, 32, 29)
        self.update()

    @property
    def available_formats(self) -> list[str]:
        return list(self._available_formats)

    @classmethod
    def active_menu_in(
        cls, parent: QWidget, exclude: Optional[RadialConversionMenu] = None
    ) -> Optional[RadialConversionMenu]:
        """Return another visible menu owned by this application window, if any."""
        return next(
            (
                menu
                for menu in parent.findChildren(cls)
                if menu is not exclude and menu.isVisible()
            ),
            None,
        )

    @property
    def target_formats(self) -> list[str]:
        return list(self._available_formats)

    @property
    def hover_index(self) -> int:
        return self._hover_index

    @property
    def selected_index(self) -> int:
        return max(0, self._hover_index) if self._hover_index >= 0 else 0

    @selected_index.setter
    def selected_index(self, val: int) -> None:
        self.set_hover_index(val)

    @property
    def primary_name(self) -> str:
        if not self.paths:
            return "Waiting for local file drop" if self.awaiting_drop else "No files"
        if len(self.paths) == 1:
            return self.paths[0].name
        return f"{len(self.paths)} files selected"

    @property
    def size_str(self) -> str:
        total = sum(p.stat().st_size for p in self.paths if p.is_file())
        return _format_size(total)

    @property
    def item_count(self) -> int:
        return len(self.paths)

    @property
    def ole_drag_active(self) -> bool:
        return self._ole_drag_active

    def _determine_formats(self) -> list[str]:
        """Compute supported target formats for the loaded file(s)."""
        return get_supported_targets(self.paths)

    def _generate_thumbnail(self) -> Optional[QPixmap]:
        """Generate a small thumbnail pixmap for the center hub."""
        if not self.paths:
            return None

        primary = self.paths[0]
        suffix = primary.suffix.lower()

        # For common image formats, load direct pixmap
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
            try:
                pix = QPixmap(str(primary))
                if not pix.isNull():
                    return pix.scaled(
                        44, 44,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            except Exception:
                pass

        return None

    def show_at_cursor(self, cursor_pos: Optional[QPoint] = None) -> None:
        """Center on the activation pointer where possible without clamping it outside the menu."""
        if cursor_pos is None:
            cursor_pos = QCursor.pos()

        # Find the screen under cursor
        screen = QGuiApplication.screenAt(cursor_pos)
        if not screen:
            screen = QGuiApplication.primaryScreen()

        geom = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        self.move(_clamped_menu_origin(cursor_pos, geom, self.size()))
        self.show()
        self.raise_()
        if self.is_overlay:
            self.activateWindow()
            self.setFocus()

    def set_hover_index(self, index: int) -> None:
        """Update the currently hovered/selected format index and repaint."""
        count = len(self._available_formats)
        if count == 0:
            new_idx = -1
        elif index < -1 or index >= count:
            new_idx = -1
        else:
            new_idx = index

        if new_idx != self._hover_index:
            self._hover_index = new_idx
            self.update()

    def _petal_center(self, index: int) -> QPointF:
        """Return the center used to draw and hit-test one petal."""
        count = len(self._available_formats)
        angle = math.radians(90.0 - index * (360.0 / count))
        offset = 8.0 if index == self._hover_index else 0.0
        orbit = self._r_orbit + offset
        return QPointF(
            self._cx + orbit * math.cos(angle),
            self._cy - orbit * math.sin(angle),
        )

    def track_drag_pos(self, pos: Any) -> int:
        """Track drag position, update hovered petal index and repaint."""
        hit = self.petal_at_pos(pos)
        self.set_hover_index(hit)
        return hit

    def navigate_next(self) -> None:
        """Move selection to the next petal clockwise."""
        count = len(self._available_formats)
        if count == 0:
            return
        if self._hover_index < 0:
            self.set_hover_index(0)
        else:
            self.set_hover_index((self._hover_index + 1) % count)

    def navigate_prev(self) -> None:
        """Move selection to previous petal counter-clockwise."""
        count = len(self._available_formats)
        if count == 0:
            return
        if self._hover_index < 0:
            self.set_hover_index(count - 1)
        else:
            self.set_hover_index((self._hover_index - 1 + count) % count)

    def confirm_selection(self, index: int) -> None:
        """Trigger conversion for the chosen format index and close the menu."""
        if 0 <= index < len(self._available_formats):
            chosen_format = self._available_formats[index]
            self._selection_confirmed = True
            self.format_selected.emit(chosen_format, self.paths)
            self.close()

    def _cancel(self) -> None:
        if not self._selection_confirmed and not self._cancelled:
            self._cancelled = True
            self.cancelled.emit()
        self.close()

    # -----------------------------------------------------------------------
    # Events: Mouse, Keyboard, and Focus
    # -----------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
        elif self.awaiting_drop:
            event.ignore()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._hover_index >= 0:
                self.confirm_selection(self._hover_index)
            elif len(self._available_formats) == 1:
                self.confirm_selection(0)
            event.accept()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.navigate_next()
            event.accept()
        elif key in (Qt.Key.Key_Backtab, Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.navigate_prev()
            event.accept()
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            num = key - Qt.Key.Key_1
            if num < len(self._available_formats):
                self.confirm_selection(num)
            event.accept()
        else:
            super().keyPressEvent(event)

    def petal_at_pos(self, pos: Any) -> int:
        """Return the index of the petal that contains *pos*, or -1 if outside.

        Uses the visible petal discs as hit targets. The current petal gets a
        small distance buffer so selection remains stable at its boundary.
        """
        count = len(self._available_formats)
        if count == 0:
            return -1

        pt = QPointF(pos.x(), pos.y()) if hasattr(pos, "x") else pos
        if 0 <= self._hover_index < count:
            center = self._petal_center(self._hover_index)
            dx, dy = pt.x() - center.x(), pt.y() - center.y()
            radius = self._r_petal + 4.0 + 8.0
            if dx * dx + dy * dy <= radius * radius:
                return self._hover_index

        nearest_index = -1
        nearest_distance = self._r_petal * self._r_petal
        for index in range(count):
            if index == self._hover_index:
                continue
            center = self._petal_center(index)
            dx, dy = pt.x() - center.x(), pt.y() - center.y()
            distance = dx * dx + dy * dy
            if distance <= nearest_distance and (nearest_index < 0 or distance < nearest_distance):
                nearest_index = index
                nearest_distance = distance
        return nearest_index

    def set_paths(self, paths: Sequence[Path]) -> None:
        """Update active files dynamically (e.g. when dragged into menu directly)."""
        self.paths = [p for p in paths if p.is_file()]
        self._available_formats = self._determine_formats()
        self._hover_index = 0 if self._available_formats and not self.awaiting_drop else -1
        self._thumbnail_pixmap = self._generate_thumbnail()
        self.update()

    def _local_file_payload(self, mime_data: Any) -> tuple[list[Path], Optional[str]]:
        if not mime_data.hasUrls():
            return [], "This source does not expose local file URLs."

        urls = mime_data.urls()
        if not urls:
            return [], "This source did not provide any files."

        paths: list[Path] = []
        for url in urls:
            if not url.isLocalFile():
                return [], "Only local files can be converted."
            path = Path(url.toLocalFile())
            try:
                if not path.is_absolute() or path.is_symlink() or not path.is_file():
                    return [], "The drop contains an invalid or unsupported file path."
                if path.stat().st_size > MAX_INPUT_BYTES:
                    return [], "A dropped file exceeds the 250 MiB input limit."
            except OSError:
                return [], "A dropped file could not be accessed."
            paths.append(path)

        if not get_supported_targets(paths):
            return [], "No common conversion target is available for these files."
        return paths, None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hit = self.petal_at_pos(event.position())
        self.set_hover_index(hit)

    # -----------------------------------------------------------------------
    # Drag & Drop: Drop files directly onto radial format petals
    # -----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._ole_drag_active = False
        paths, error = self._local_file_payload(event.mimeData())
        if error:
            self._drop_message = error
            self._hover_index = -1
            self.update()
            log.info("OLE drag rejected: %s", error)
            event.ignore()
            return

        self._drop_message = None
        self._ole_drag_active = True
        if paths != self.paths:
            self.set_paths(paths)
        log.info("OLE drag accepted for preview: %d local file(s), %d target(s).", len(paths), len(self._available_formats))
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self.paths and self._available_formats:
            hit = self.petal_at_pos(event.position())
            self.set_hover_index(hit)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        self._ole_drag_active = False
        target_paths, error = self._local_file_payload(event.mimeData())
        if error:
            self._drop_message = error
            self._hover_index = -1
            self.update()
            log.info("OLE drop rejected: %s", error)
            self.ole_drag_left.emit()
            event.ignore()
            return
        if target_paths != self.paths:
            self.set_paths(target_paths)

        hit = self.petal_at_pos(event.position())
        if 0 <= hit < len(self._available_formats):
            self.confirm_selection(hit)
            event.acceptProposedAction()
        else:
            self._drop_message = "Drop directly on a format sector; no file was converted."
            self._hover_index = -1
            self.update()
            log.info("OLE drop rejected: drop position did not hit a format sector.")
            self.ole_drag_left.emit()
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._ole_drag_active = False
        self.ole_drag_left.emit()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.awaiting_drop:
            hit = self.petal_at_pos(event.position())
            self.set_hover_index(hit)
            if hit >= 0:
                self.confirm_selection(hit)
            else:
                self._cancel()
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._selection_confirmed and not self._cancelled:
            self._cancelled = True
            self.cancelled.emit()
        super().closeEvent(event)

    def changeEvent(self, event: Any) -> None:
        super().changeEvent(event)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._cx = self.width() / 2.0
        self._cy = self.height() / 2.0

    def setGeometry(self, *args: Any) -> None:
        super().setGeometry(*args)
        self._cx = self.width() / 2.0
        self._cy = self.height() / 2.0

    # -----------------------------------------------------------------------
    # Rendering: Vector radial segments, hub, badges, and headers
    # -----------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        count = len(self._available_formats)

        # 0. In overlay mode, dim the application behind the wheel.
        if self.is_overlay:
            painter.fillRect(self.rect(), self._c_overlay)

        # 1. Floating Top Filename Pill
        self._paint_top_pill(painter)

        # 2. Orbital Ring Line
        painter.setBrush(Qt.BrushStyle.NoBrush)
        orbit_color = QColor(self._c_border)
        orbit_color.setAlpha(110)
        painter.setPen(QPen(orbit_color, 1.0))
        painter.drawEllipse(QPointF(self._cx, self._cy), self._r_orbit, self._r_orbit)

        # 3. Radial Petals
        if count > 0:
            for i, fmt in enumerate(self._available_formats):
                is_hovered = (i == self._hover_index)
                petal_center = self._petal_center(i)
                px, py = petal_center.x(), petal_center.y()
                pr = self._r_petal + (4.0 if is_hovered else 0.0)

                # Petal Circle
                if is_hovered:
                    painter.setBrush(QBrush(self._c_hover))
                    painter.setPen(QPen(self._c_border_hover, 2.0))
                else:
                    painter.setBrush(QBrush(self._c_card))
                    painter.setPen(QPen(self._c_border, 1.0))

                painter.drawEllipse(petal_center, pr, pr)

                # Format label text
                painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
                painter.setPen(self._c_text_white)
                label = fmt.upper()
                text_rect = QRectF(px - pr + 2, py - 14, (pr - 2) * 2, 28)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
        else:
            painter.setBrush(QBrush(self._c_card))
            painter.setPen(QPen(self._c_border, 1.0))
            painter.drawEllipse(QPointF(self._cx, self._cy), self._r_outer, self._r_outer)

        # 4. Center Hub Circle matching Mockup 3
        self._paint_center_hub(painter)

        # 5. Floating Bottom Hint Pill
        self._paint_bottom_pill(painter)

    def _paint_top_pill(self, painter: QPainter) -> None:
        """Draw top pill card showing filename and file count."""
        pill_rect = self._top_pill_rect()
        painter.setBrush(QBrush(self._c_bg))
        painter.setPen(QPen(self._c_border, 1.0))
        painter.drawRoundedRect(pill_rect, 14, 14)

        if not self.paths and self.awaiting_drop:
            title = "Drop local files here"
        elif not self.paths:
            title = "No files selected"
        elif len(self.paths) == 1:
            title = self.paths[0].name
        else:
            title = f"{len(self.paths)} files selected"

        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(self._c_text_white)
        fm = painter.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideMiddle, int(pill_rect.width() - 20))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, elided)

    def _pill_rect(self, width: float, height: float, center_y: float) -> QRectF:
        width = min(width, max(1.0, self.width() - 16.0))
        height = min(height, max(1.0, self.height() - 16.0))
        left = (self.width() - width) / 2.0
        top = min(max(center_y - height / 2.0, 8.0), self.height() - height - 8.0)
        return QRectF(left, top, width, height)

    def _top_pill_rect(self) -> QRectF:
        extent = self._r_orbit + self._r_petal + 12.0
        return self._pill_rect(260.0, 28.0, self._cy - extent - 22.0)

    def _paint_center_hub(self, painter: QPainter) -> None:
        """Draw a quiet source-file hub."""
        hub_center = QPointF(self._cx, self._cy)
        painter.setBrush(QBrush(self._c_hub))
        painter.setPen(QPen(self._c_border, 1.5))
        painter.drawEllipse(hub_center, self._r_inner, self._r_inner)

        if self._thumbnail_pixmap and not self._thumbnail_pixmap.isNull():
            pw = self._thumbnail_pixmap.width()
            ph = self._thumbnail_pixmap.height()
            painter.drawPixmap(int(self._cx - pw / 2.0), int(self._cy - ph / 2.0), self._thumbnail_pixmap)
        else:
            paper = QRectF(self._cx - 12, self._cy - 17, 24, 34)
            painter.setBrush(QBrush(self._c_card))
            painter.setPen(QPen(self._c_border_hover, 1.5))
            painter.drawRoundedRect(paper, 2, 2)
            painter.setPen(QPen(self._c_border, 1.0))
            for y in (-7, 0, 7):
                painter.drawLine(
                    QPointF(self._cx - 6, self._cy + y),
                    QPointF(self._cx + 6, self._cy + y),
                )

    def _paint_bottom_pill(self, painter: QPainter) -> None:
        """Draw bottom hint pill with target preview or navigation help."""
        pill_rect = self._bottom_pill_rect()

        painter.setBrush(QBrush(self._c_bg))
        painter.setPen(QPen(self._c_border, 1.0))
        painter.drawRoundedRect(pill_rect, 15, 15)

        if self._drop_message:
            hint = self._drop_message
            color = self._c_border_hover
        elif self.awaiting_drop and not self.paths:
            hint = "Drop local files on a format • virtual files need Open Files"
            color = self._c_text_muted
        elif self._hover_index >= 0 and self._hover_index < len(self._available_formats):
            fmt = self._available_formats[self._hover_index]
            label = FORMAT_LABELS.get(fmt, fmt.upper())
            hint = f"Convert to {label} (.{fmt}) · Enter or click"
            color = self._c_text_accent
        elif not self._available_formats:
            hint = "No supported conversion routes available"
            color = self._c_border_hover
        else:
            hint = "Choose a format · arrow keys move · Esc cancels"
            color = self._c_text_muted

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        painter.setPen(color)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, hint)

    def _bottom_pill_rect(self) -> QRectF:
        extent = self._r_orbit + self._r_petal + 12.0
        return self._pill_rect(300.0, 30.0, self._cy + extent + 22.0)


class ShiftActivationFilter(QObject):
    """Application-scoped event filter for safe Shift gesture activation.

    Rules:
    - Never intercepts key events when the active focus is a text entry widget
      (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox) so standard typing
      (capital letters, shifted punctuation, text selection) is never broken.
    - Activates when:
      1. Shift + Space or Shift + Right-Click is pressed.
      2. The user holds Shift while dragging files into the window.
      3. Shift key is tapped while files are selected in the queue.
    - Pure PySide6 QObject event filter. Zero native global hooks.
    """

    shift_invoked = Signal(object)  # emits cursor QPoint or None

    def __init__(
        self,
        main_window: Optional[QWidget] = None,
        get_active_files: Optional[Callable[[], Sequence[Path]]] = None,
        on_format_selected: Optional[Callable[[str, list[Path]], None]] = None,
    ):
        super().__init__(main_window)
        self.main_window = main_window
        self.get_active_files = get_active_files or (lambda: [])
        self.on_format_selected = on_format_selected or (lambda fmt, pths: None)
        self._active_menu: Optional[RadialConversionMenu] = None

    def trigger(self, paths: Optional[Sequence[Path]] = None, pos: Optional[QPoint] = None) -> bool:
        """Trigger the radial conversion menu with the given paths or active files."""
        target_paths = list(paths) if paths is not None else list(self.get_active_files())
        if not target_paths:
            if self._active_menu and self._active_menu.isVisible():
                self._active_menu.close()
                self._active_menu = None
            return False

        if self._active_menu and self._active_menu.isVisible():
            if paths is not None and set(target_paths) != set(self._active_menu.paths):
                self._active_menu.set_paths(target_paths)
                return True
            self._active_menu.close()
            self._active_menu = None
            return False

        if self.main_window:
            if RadialConversionMenu.active_menu_in(self.main_window):
                return False
            controller = getattr(self.main_window, "bg_controller", None)
            background_menu = getattr(controller, "_active_menu", None)
            if background_menu and background_menu.isVisible():
                return False

        # Verify there are supported conversion routes
        menu = RadialConversionMenu(target_paths, parent=self.main_window)
        if not menu.available_formats:
            # No supported conversion routes for this file type
            menu.deleteLater()
            return False

        def _on_selected(fmt: str, pths: list[Path]) -> None:
            self.on_format_selected(fmt, pths)
            self._active_menu = None

        def _on_closed() -> None:
            self._active_menu = None

        menu.format_selected.connect(_on_selected)
        menu.cancelled.connect(_on_closed)
        self._active_menu = menu
        self.shift_invoked.emit(pos or QCursor.pos())
        menu.show_at_cursor(pos or QCursor.pos())
        return True

    def eventFilter(self, watched: QObject, event: Any) -> bool:
        from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QSpinBox, QTextEdit

        # 1. Protect all text inputs from gesture interception
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox)) or isinstance(
            watched, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox)
        ):
            return super().eventFilter(watched, event)

        evt_type = event.type()

        # 2. Key events
        if evt_type == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()

            # Shift + Space shortcut
            if key == Qt.Key.Key_Space and (mods & Qt.KeyboardModifier.ShiftModifier):
                self.shift_invoked.emit(QCursor.pos())
                self.trigger()
                return True

            # Standalone Shift keypress when files are selected or window active
            if key == Qt.Key.Key_Shift and not (
                mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            ):
                files = self.get_active_files()
                if files:
                    if self.trigger(paths=files):
                        return True

        # 3. Shift + Right-Click mouse events
        elif evt_type == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.RightButton and (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                files = self.get_active_files()
                if files:
                    if self.trigger(paths=files, pos=QCursor.pos()):
                        return True

        return super().eventFilter(watched, event)
