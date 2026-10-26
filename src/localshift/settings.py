"""
localshift.settings — Centralized persistent configuration and destination resolution.

Responsibilities:
- Persist application settings (Save to Folder, appearance/theme, gesture preferences)
  across sessions via QSettings.
- Single unified output destination resolution policy:
    1. Explicit per-job destination supplied by the user.
    2. Global custom destination when enabled and valid.
    3. Existing workflow default (e.g. source file directory).
- Destination directory validation (existence, directory type, write permissions).
- Sensible first-launch defaults (Downloads folder).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QCoreApplication, QObject, QSettings, Signal

log = logging.getLogger(__name__)

# Standard application metadata for QSettings
ORGANIZATION_NAME = "LocalShift"
APPLICATION_NAME = "LocalShift"


def get_default_save_folder() -> Path:
    """Return a sensible default save folder for the current user."""
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads
    docs = Path.home() / "Documents" / "LocalShift"
    return docs


def validate_destination_directory(path: Optional[Path]) -> tuple[bool, str]:
    """Validate that *path* is an accessible, writable directory.

    Returns:
        (is_valid, error_message). If valid, error_message is empty.
    """
    if path is None:
        return False, "No destination folder specified."

    try:
        p = Path(path).resolve()
    except Exception as exc:
        return False, f"Invalid path syntax: {exc}"

    if not p.exists():
        # Check if parent exists and is writable so we could create it if needed
        try:
            if p.parent.exists() and os.access(str(p.parent), os.W_OK):
                return True, ""  # Can be created on demand
        except OSError:
            pass
        return False, f"Directory does not exist: {p}"

    if not p.is_dir():
        return False, f"Path is not a directory: {p}"

    # Check write permissions
    try:
        if not os.access(str(p), os.W_OK):
            return False, f"Directory is not writable: {p}"
        # Test creating a temporary sentinel to confirm true write access on Windows
        test_file = p / ".localshift_write_test.tmp"
        try:
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
        except (OSError, PermissionError) as exc:
            return False, f"Write permission denied in directory: {exc}"
    except (OSError, PermissionError) as exc:
        return False, f"Inaccessible directory: {exc}"

    return True, ""


class AppSettings(QObject):
    """Centralized application configuration service.

    Emits `changed` signal whenever any persistent setting is modified.
    """

    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._qsettings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self._load()

    def _load(self) -> None:
        """Load settings from QSettings or establish first-launch defaults."""
        raw_enabled = self._qsettings.value("save_to_folder_enabled", False)
        # Convert QSettings string/bool variants
        if isinstance(raw_enabled, str):
            self._save_to_folder_enabled = raw_enabled.lower() in ("true", "1", "yes")
        else:
            self._save_to_folder_enabled = bool(raw_enabled)

        raw_folder = self._qsettings.value("save_to_folder_path", None)
        if raw_folder and str(raw_folder).strip():
            self._save_to_folder_path: Path = Path(str(raw_folder))
        else:
            self._save_to_folder_path = get_default_save_folder()

        self._theme: str = str(self._qsettings.value("theme", "dark"))
        self._radial_gesture_enabled: bool = bool(self._qsettings.value("radial_gesture_enabled", True))

    @property
    def save_to_folder_enabled(self) -> bool:
        """Whether the global custom destination folder is enabled."""
        return self._save_to_folder_enabled

    @save_to_folder_enabled.setter
    def save_to_folder_enabled(self, value: bool) -> None:
        if self._save_to_folder_enabled != value:
            self._save_to_folder_enabled = bool(value)
            self._qsettings.setValue("save_to_folder_enabled", self._save_to_folder_enabled)
            self._qsettings.sync()
            self.changed.emit()

    @property
    def save_to_folder_path(self) -> Path:
        """The persistent destination folder path."""
        return self._save_to_folder_path

    @save_to_folder_path.setter
    def save_to_folder_path(self, path: Path) -> None:
        p = Path(path).resolve()
        if self._save_to_folder_path != p:
            self._save_to_folder_path = p
            self._qsettings.setValue("save_to_folder_path", str(p))
            self._qsettings.sync()
            self.changed.emit()

    @property
    def theme(self) -> str:
        return self._theme

    @theme.setter
    def theme(self, value: str) -> None:
        val = "light" if value.lower() == "light" else "dark"
        if self._theme != val:
            self._theme = val
            self._qsettings.setValue("theme", val)
            self._qsettings.sync()
            self.changed.emit()

    @property
    def radial_gesture_enabled(self) -> bool:
        return self._radial_gesture_enabled

    @radial_gesture_enabled.setter
    def radial_gesture_enabled(self, value: bool) -> None:
        if self._radial_gesture_enabled != value:
            self._radial_gesture_enabled = bool(value)
            self._qsettings.setValue("radial_gesture_enabled", self._radial_gesture_enabled)
            self._qsettings.sync()
            self.changed.emit()

    @property
    def history(self) -> list[dict[str, Any]]:
        """Return list of recent conversion history entries."""
        raw = self._qsettings.value("recent_history", [])
        if isinstance(raw, list):
            return raw
        return []

    def add_history_entry(self, name: str, route: str, size_str: str, path: str) -> None:
        """Add a successful conversion record to persistent history (bounded to 20)."""
        entries = list(self.history)
        new_entry = {
            "name": name,
            "route": route,
            "size": size_str,
            "path": str(path),
        }
        entries = [e for e in entries if isinstance(e, dict) and e.get("path") != str(path)]
        entries.insert(0, new_entry)
        entries = entries[:20]
        self._qsettings.setValue("recent_history", entries)
        self._qsettings.sync()
        self.changed.emit()

    def resolve_destination(
        self,
        explicit_dest: Optional[Path] = None,
        fallback_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Resolve the final output destination according to LocalShift precedence rules.

        Precedence:
        1. Explicit per-job destination supplied by the user (if specified and valid).
        2. Global custom destination folder when enabled and valid.
        3. Existing workflow fallback directory (typically source file's parent folder).

        Parameters:
            explicit_dest: Per-job destination explicitly chosen in the tab/command.
            fallback_dir: Default fallback directory (e.g. source file's directory).

        Returns:
            Resolved output directory Path, or None if no destination could be resolved.
        """
        # 1. Explicit per-job destination
        if explicit_dest is not None:
            p = Path(explicit_dest)
            if str(p).strip():
                return p

        # 2. Global custom destination when enabled
        if self._save_to_folder_enabled:
            target = self._save_to_folder_path
            valid, err = validate_destination_directory(target)
            if valid:
                if not target.exists():
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    except OSError as exc:
                        log.warning("Could not auto-create save folder %s: %s", target, exc)
                        # Fall through to fallback
                    else:
                        return target
                else:
                    return target
            else:
                log.warning("Global save folder invalid: %s (%s). Falling back.", target, err)

        # 3. Workflow default fallback
        if fallback_dir is not None:
            return Path(fallback_dir)

        return None


# Global settings singleton
_global_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    """Return the global AppSettings singleton instance."""
    global _global_settings
    if _global_settings is None:
        _global_settings = AppSettings()
    return _global_settings
