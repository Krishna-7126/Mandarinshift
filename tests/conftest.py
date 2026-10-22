"""
conftest.py — Shared pytest fixtures for LocalShift tests.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from PIL import Image


# ---------------------------------------------------------------------------
# Image factory helpers
# ---------------------------------------------------------------------------

def _make_rgba_png(path: Path, size: tuple[int, int] = (9, 7)) -> Path:
    """Create a small RGBA PNG with partial transparency at *path*."""
    Image.new("RGBA", size, (240, 20, 30, 120)).save(path, format="PNG")
    return path


def _make_rgb_jpeg(path: Path, size: tuple[int, int] = (8, 6)) -> Path:
    """Create a small RGB JPEG at *path*."""
    Image.new("RGB", size, (10, 200, 50)).save(path, format="JPEG")
    return path


def _make_rgb_png(path: Path, size: tuple[int, int] = (10, 10)) -> Path:
    """Create a small opaque RGB PNG at *path*."""
    Image.new("RGB", size, (100, 150, 200)).save(path, format="PNG")
    return path


def _make_l_png(path: Path, size: tuple[int, int] = (8, 8)) -> Path:
    """Create a small grayscale PNG at *path*."""
    Image.new("L", size, 128).save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rgba_png(tmp_path) -> Path:
    """RGBA PNG fixture with partial transparency."""
    return _make_rgba_png(tmp_path / "rgba.png")


@pytest.fixture()
def rgb_png(tmp_path) -> Path:
    """Opaque RGB PNG fixture."""
    return _make_rgb_png(tmp_path / "rgb.png")


@pytest.fixture()
def rgb_jpeg(tmp_path) -> Path:
    """Opaque RGB JPEG fixture."""
    return _make_rgb_jpeg(tmp_path / "rgb.jpg")


@pytest.fixture()
def gray_png(tmp_path) -> Path:
    """Grayscale PNG fixture."""
    return _make_l_png(tmp_path / "gray.png")


@pytest.fixture()
def text_file(tmp_path) -> Path:
    """A file with .png extension containing plain text (not a valid image)."""
    p = tmp_path / "fake.png"
    p.write_text("this is definitely not an image", encoding="utf-8")
    return p
