"""
tests/test_settings.py — Unit tests for centralized persistent settings and destination policy.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from localshift.settings import (
    AppSettings,
    get_default_save_folder,
    get_settings,
    validate_destination_directory,
)


@pytest.fixture
def clean_settings(tmp_path: Path):
    """Fixture providing an isolated AppSettings instance."""
    from PySide6.QtCore import QSettings
    # Use isolated test key
    s = AppSettings()
    # Reset state
    s.save_to_folder_enabled = False
    s.save_to_folder_path = tmp_path / "custom_out"
    s.theme = "dark"
    return s


class TestAppSettings:
    def test_global_radial_conversion_is_off_by_default(self, monkeypatch):
        class EmptySettings:
            def value(self, key, default=None):
                return default

        monkeypatch.setattr("localshift.settings.QSettings", lambda *args: EmptySettings())
        assert AppSettings().radial_gesture_enabled is False

    @pytest.mark.parametrize(("stored_value", "expected"), [("false", False), ("true", True), ("0", False), ("1", True)])
    def test_radial_preference_parses_persisted_string_values(self, monkeypatch, stored_value, expected):
        class StoredSettings:
            def value(self, key, default=None):
                if key == "radial_gesture_enabled":
                    return stored_value
                return default

        monkeypatch.setattr("localshift.settings.QSettings", lambda *args: StoredSettings())
        assert AppSettings().radial_gesture_enabled is expected

    def test_default_save_folder_exists(self):
        folder = get_default_save_folder()
        assert isinstance(folder, Path)
        assert folder.is_dir() or folder.parent.is_dir()

    def test_settings_persistence(self, clean_settings: AppSettings, tmp_path: Path):
        s = clean_settings
        assert s.save_to_folder_enabled is False

        s.save_to_folder_enabled = True
        assert s.save_to_folder_enabled is True

        new_path = tmp_path / "new_dest"
        new_path.mkdir(parents=True, exist_ok=True)
        s.save_to_folder_path = new_path
        assert s.save_to_folder_path == new_path.resolve()

        s.theme = "light"
        assert s.theme == "light"
        s.theme = "dark"
        assert s.theme == "dark"

    def test_validate_destination_directory(self, tmp_path: Path):
        # 1. Existing writable directory
        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()
        ok, msg = validate_destination_directory(valid_dir)
        assert ok is True
        assert msg == ""

        # 2. None path
        ok, msg = validate_destination_directory(None)
        assert ok is False
        assert "No destination" in msg

        # 3. File instead of directory
        a_file = tmp_path / "file.txt"
        a_file.touch()
        ok, msg = validate_destination_directory(a_file)
        assert ok is False
        assert "not a directory" in msg

        # 4. Nonexistent directory whose parent does NOT exist
        nested_bad = tmp_path / "no_such_parent" / "sub" / "leaf"
        ok, msg = validate_destination_directory(nested_bad)
        assert ok is False


class TestDestinationPrecedence:
    def test_explicit_destination_takes_highest_precedence(self, clean_settings: AppSettings, tmp_path: Path):
        s = clean_settings
        s.save_to_folder_enabled = True
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        s.save_to_folder_path = global_dir

        explicit = tmp_path / "explicit"
        fallback = tmp_path / "fallback"

        resolved = s.resolve_destination(explicit_dest=explicit, fallback_dir=fallback)
        assert resolved == explicit

    def test_global_destination_used_when_enabled(self, clean_settings: AppSettings, tmp_path: Path):
        s = clean_settings
        s.save_to_folder_enabled = True
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        s.save_to_folder_path = global_dir

        fallback = tmp_path / "fallback"

        resolved = s.resolve_destination(explicit_dest=None, fallback_dir=fallback)
        assert resolved == global_dir

    def test_fallback_used_when_global_disabled(self, clean_settings: AppSettings, tmp_path: Path):
        s = clean_settings
        s.save_to_folder_enabled = False
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        s.save_to_folder_path = global_dir

        fallback = tmp_path / "fallback"

        resolved = s.resolve_destination(explicit_dest=None, fallback_dir=fallback)
        assert resolved == fallback

    def test_fallback_used_when_global_inaccessible(self, clean_settings: AppSettings, tmp_path: Path):
        s = clean_settings
        s.save_to_folder_enabled = True
        # Set to impossible / inaccessible path
        s.save_to_folder_path = tmp_path / "ghost_parent" / "ghost_child"

        fallback = tmp_path / "fallback"

        resolved = s.resolve_destination(explicit_dest=None, fallback_dir=fallback)
        assert resolved == fallback
