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



# Design tokens for radial menu (tuples prevent global QColor destruction crashes at process exit)
COLOR_RADIAL_BG = (15, 23, 42, 235)           # Slate 900 semi-translucent
COLOR_RADIAL_CARD = (30, 41, 59, 245)         # Slate 800
COLOR_RADIAL_HOVER = (99, 102, 241, 255)       # Electric Indigo Accent
COLOR_RADIAL_BORDER = (51, 65, 85, 200)        # Slate 700
COLOR_RADIAL_BORDER_HOVER = (165, 180, 252, 255) # Indigo 300 glow
COLOR_RADIAL_TEXT_WHITE = (248, 250, 252, 255)
COLOR_RADIAL_TEXT_MUTED = (148, 163, 184, 255)
COLOR_RADIAL_TEXT_ACCENT = (129, 140, 248, 255)
COLOR_RADIAL_BLUE_GRAD_START = (59, 130, 246, 255) # Blue 500
COLOR_RADIAL_BLUE_GRAD_END = (129, 140, 248, 255)   # Indigo 400


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024.0
    return f"{mb:.1f} MB"


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

    def __init__(
        self,
        paths: Sequence[Path],
        parent: Optional[QWidget] = None,
        output_dir: Optional[Path] = None,
        is_overlay: bool = False,
    ):
        super().__init__(parent)
        self.paths: list[Path] = [p for p in paths if p.is_file()]
        self.output_dir = output_dir
        self.is_overlay = is_overlay

        # Geometry dimensions
        self._wheel_size = 400
        self.resize(self._wheel_size, self._wheel_size + 60)
        self._cx = self.width() / 2.0
        self._cy = (self._wheel_size / 2.0) + 20.0
        self._r_inner = 58.0
        self._r_outer = 138.0
        self._r_orbit = 104.0
        self._r_petal = 40.0

        # State
        self._available_formats: list[str] = self._determine_formats()
        self._hover_index: int = 0 if self._available_formats else -1
        self._thumbnail_pixmap: Optional[QPixmap] = self._generate_thumbnail()

        # Instance color tokens
        self._c_bg = QColor(*COLOR_RADIAL_BG)
        self._c_card = QColor(*COLOR_RADIAL_CARD)
        self._c_hover = QColor(*COLOR_RADIAL_HOVER)
        self._c_border = QColor(*COLOR_RADIAL_BORDER)
        self._c_border_hover = QColor(*COLOR_RADIAL_BORDER_HOVER)
        self._c_text_white = QColor(*COLOR_RADIAL_TEXT_WHITE)
        self._c_text_muted = QColor(*COLOR_RADIAL_TEXT_MUTED)
        self._c_text_accent = QColor(*COLOR_RADIAL_TEXT_ACCENT)

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

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if is_overlay else Qt.FocusPolicy.NoFocus)
        self.setAcceptDrops(True)

    @property
    def available_formats(self) -> list[str]:
        return list(self._available_formats)

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
            return "No files"
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
        """Position the menu centered at cursor_pos, clamped safely to screen boundaries."""
        if cursor_pos is None:
            cursor_pos = QCursor.pos()

        # Find the screen under cursor
        screen = QGuiApplication.screenAt(cursor_pos)
        if not screen:
            screen = QGuiApplication.primaryScreen()

        geom = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        menu_w = self.width()
        menu_h = self.height()

        target_x = cursor_pos.x() - menu_w // 2
        target_y = cursor_pos.y() - menu_h // 2

        # Clamp with 10px margin to ensure 100% visibility on all screens
        margin = 10
        clamped_x = max(geom.left() + margin, min(target_x, geom.right() - menu_w - margin))
        clamped_y = max(geom.top() + margin, min(target_y, geom.bottom() - menu_h - margin))

        self.move(int(clamped_x), int(clamped_y))
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
            self.format_selected.emit(chosen_format, self.paths)
            self.close()

    # -----------------------------------------------------------------------
    # Events: Mouse, Keyboard, and Focus
    # -----------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            event.accept()
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

        Uses stable polar coordinate sectors with boundary hysteresis and
        disc proximity to eliminate edge oscillation and jitter.
        """
        count = len(self._available_formats)
        if count == 0:
            return -1

        pt = QPointF(pos.x(), pos.y()) if hasattr(pos, "x") else pos
        dx = pt.x() - self._cx
        dy = pt.y() - self._cy
        dist = math.hypot(dx, dy)

        # 1. Distance rejection with buffer
        min_r = self._r_inner - 10.0
        max_r = self._r_outer + 35.0
        if self._hover_index >= 0:
            min_r -= 6.0
            max_r += 12.0

        if dist < min_r or dist > max_r:
            return -1

        step_deg = 360.0 / count

        # 2. Disc proximity check
        for i in range(count):
            angle_rad = math.radians(90.0 - i * step_deg)
            pcx = self._cx + self._r_orbit * math.cos(angle_rad)
            pcy = self._cy - self._r_orbit * math.sin(angle_rad)
            disc_dist = math.hypot(pt.x() - pcx, pt.y() - pcy)
            threshold = self._r_petal + (8.0 if i == self._hover_index else 0.0)
            if disc_dist <= threshold:
                return i

        # 3. Polar sector angle with hysteresis
        angle_rad = math.atan2(-(pt.y() - self._cy), pt.x() - self._cx)
        deg = math.degrees(angle_rad) % 360.0
        clock_deg = (90.0 - deg) % 360.0

        # Sticky bias for currently hovered petal
        if 0 <= self._hover_index < count:
            center_deg = (self._hover_index * step_deg) % 360.0
            diff = abs((clock_deg - center_deg + 180.0) % 360.0 - 180.0)
            hysteresis_deg = min(6.0, step_deg * 0.18)
            if diff <= (step_deg / 2.0) + hysteresis_deg:
                return self._hover_index

        raw_idx = int((clock_deg + (step_deg / 2.0)) / step_deg) % count
        return raw_idx

    def set_paths(self, paths: Sequence[Path]) -> None:
        """Update active files dynamically (e.g. when dragged into menu directly)."""
        self.paths = [p for p in paths if p.is_file()]
        self._available_formats = self._determine_formats()
        self._hover_index = 0 if self._available_formats else -1
        self._thumbnail_pixmap = self._generate_thumbnail()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hit = self.petal_at_pos(event.position())
        self.set_hover_index(hit)

    # -----------------------------------------------------------------------
    # Drag & Drop: Drop files directly onto radial format petals
    # -----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
            if urls and urls != self.paths:
                self.set_paths(urls)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            hit = self.petal_at_pos(event.position())
            if hit >= 0:
                self.set_hover_index(hit)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        target_paths = urls if urls else self.paths
        if urls and urls != self.paths:
            self.set_paths(urls)

        hit = self.petal_at_pos(event.position())
        chosen: Optional[str] = None
        if hit >= 0 and hit < len(self._available_formats):
            chosen = self._available_formats[hit]
        elif self._hover_index >= 0 and self._hover_index < len(self._available_formats):
            chosen = self._available_formats[self._hover_index]
        elif len(self._available_formats) == 1:
            chosen = self._available_formats[0]

        if chosen and target_paths:
            self.format_selected.emit(chosen, target_paths)
            self.close()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._hover_index >= 0:
                self.confirm_selection(self._hover_index)
                event.accept()
                return

            # Check if clicked outside the radial wheel to dismiss
            pos = event.position()
            dist = math.hypot(pos.x() - self._cx, pos.y() - self._cy)
            if dist > self._r_outer + 50 or dist < self._r_inner * 0.4:
                self.cancelled.emit()
                self.close()
                event.accept()
                return

        super().mousePressEvent(event)

    def changeEvent(self, event: Any) -> None:
        super().changeEvent(event)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._cx = self.width() / 2.0
        self._cy = self.height() / 2.0 if self.is_overlay else ((self._wheel_size / 2.0) + 20.0)

    def setGeometry(self, *args: Any) -> None:
        super().setGeometry(*args)
        self._cx = self.width() / 2.0
        self._cy = self.height() / 2.0 if self.is_overlay else ((self._wheel_size / 2.0) + 20.0)

    # -----------------------------------------------------------------------
    # Rendering: Vector radial segments, hub, badges, and headers
    # -----------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        count = len(self._available_formats)

        # 0. In overlay mode, draw dimmed window backdrop matching Mockup 3
        if self.is_overlay:
            painter.fillRect(self.rect(), QColor(11, 15, 25, 232))
            painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
            painter.setPen(QColor(226, 232, 240, 220))
            painter.drawText(QRectF(0, 36, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "Release Shift or pick a conversion")

        # 1. Floating Top Filename Pill
        self._paint_top_pill(painter)

        # 2. Orbital Ring Line
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(148, 163, 184, 45), 1.5))
        painter.drawEllipse(QPointF(self._cx, self._cy), self._r_orbit, self._r_orbit)

        # 3. Radial Petals
        if count > 0:
            total_deg = 360.0 / count
            gap_deg = min(4.5, total_deg * 0.15) if count > 1 else 0.0
            sweep_deg = -(total_deg - gap_deg)

            for i, fmt in enumerate(self._available_formats):
                is_hovered = (i == self._hover_index)
                start_deg = 90.0 - i * total_deg - (gap_deg / 2.0 if count > 1 else 0.0)
                mid_deg = start_deg + sweep_deg / 2.0
                mid_rad = math.radians(mid_deg)
                offset = 8.0 if is_hovered else 0.0

                # Calculate petal center
                orbit_r = self._r_orbit + offset
                px = self._cx + orbit_r * math.cos(mid_rad)
                py = self._cy - orbit_r * math.sin(mid_rad)
                pr = self._r_petal + (4.0 if is_hovered else 0.0)

                # Petal Circle
                petal_center = QPointF(px, py)
                if is_hovered:
                    # Glowing indigo hover disc
                    painter.setBrush(QBrush(QColor(*COLOR_RADIAL_HOVER)))
                    painter.setPen(QPen(QColor(*COLOR_RADIAL_BORDER_HOVER), 2.5))
                else:
                    painter.setBrush(QBrush(QColor(*COLOR_RADIAL_CARD)))
                    painter.setPen(QPen(QColor(*COLOR_RADIAL_BORDER), 1.5))

                painter.drawEllipse(petal_center, pr, pr)

                # Key number badge (1..9)
                if i < 9:
                    badge_rect = QRectF(px - pr + 4, py - pr + 4, 16, 16)
                    painter.setBrush(QBrush(QColor(15, 23, 42, 160)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(badge_rect)
                    painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                    painter.setPen(QColor(148, 163, 184, 220))
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(i + 1))

                # Format label text
                painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                painter.setPen(QColor(*COLOR_RADIAL_TEXT_WHITE))
                label = fmt.upper()
                text_rect = QRectF(px - pr + 4, py - 12, (pr - 4) * 2, 24)
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
        pill_rect = QRectF(self.width() / 2.0 - 130, 2, 260, 28)
        painter.setBrush(QBrush(self._c_bg))
        painter.setPen(QPen(self._c_border, 1.0))
        painter.drawRoundedRect(pill_rect, 14, 14)

        if not self.paths:
            title = "No files selected"
        elif len(self.paths) == 1:
            title = self.paths[0].name
        else:
            title = f"{len(self.paths)} files selected"

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(self._c_text_white)
        fm = painter.fontMetrics()
        elided = fm.elidedText(title, Qt.TextElideMode.ElideMiddle, 240)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, elided)

    def _paint_center_hub(self, painter: QPainter) -> None:
        """Draw central circle with glowing gradient hub matching Mockup 3."""
        from PySide6.QtGui import QLinearGradient

        hub_center = QPointF(self._cx, self._cy)

        # Gradient circle matching Mockup 3
        grad = QLinearGradient(
            self._cx - self._r_inner, self._cy - self._r_inner,
            self._cx + self._r_inner, self._cy + self._r_inner
        )
        grad.setColorAt(0.0, QColor(59, 130, 246))
        grad.setColorAt(1.0, QColor(129, 140, 248))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(199, 210, 254, 220), 2.0))
        painter.drawEllipse(hub_center, self._r_inner, self._r_inner)

        # Center icon or thumbnail
        if self._thumbnail_pixmap and not self._thumbnail_pixmap.isNull():
            pw = self._thumbnail_pixmap.width()
            ph = self._thumbnail_pixmap.height()
            painter.drawPixmap(int(self._cx - pw / 2.0), int(self._cy - 20), self._thumbnail_pixmap)
        else:
            painter.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(self._cx - 30, self._cy - 26, 60, 36), Qt.AlignmentFlag.AlignCenter, "✦")

        # File size badge
        size_str = ""
        if len(self.paths) == 1:
            try:
                size_str = _format_size(self.paths[0].stat().st_size)
            except OSError:
                size_str = "—"
        elif len(self.paths) > 1:
            try:
                total_bytes = sum(p.stat().st_size for p in self.paths)
                size_str = f"{len(self.paths)} files • {_format_size(total_bytes)}"
            except OSError:
                size_str = f"{len(self.paths)} files"

        if size_str:
            badge_rect = QRectF(self._cx - 46, self._cy + 10, 92, 18)
            painter.setBrush(QBrush(QColor(255, 255, 255, 20)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge_rect, 9, 9)

            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(self._c_text_muted)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, size_str)

    def _paint_bottom_pill(self, painter: QPainter) -> None:
        """Draw bottom hint pill with target preview or navigation help."""
        bottom_y = self._wheel_size + 18
        pill_rect = QRectF(self.width() / 2.0 - 150, bottom_y, 300, 30)

        painter.setBrush(QBrush(self._c_bg))
        painter.setPen(QPen(self._c_border, 1.0))
        painter.drawRoundedRect(pill_rect, 15, 15)

        if self._hover_index >= 0 and self._hover_index < len(self._available_formats):
            fmt = self._available_formats[self._hover_index]
            label = FORMAT_LABELS.get(fmt, fmt.upper())
            hint = f"Convert to {label} (. {fmt})  •  Enter / Click"
            color = self._c_text_accent
        elif not self._available_formats:
            hint = "No supported conversion routes available"
            color = QColor(248, 113, 113)  # Red 400
        else:
            hint = "Hover format or use Arrows  •  Esc to close"
            color = self._c_text_muted

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        painter.setPen(color)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, hint)


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

