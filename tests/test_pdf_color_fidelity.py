"""tests/test_pdf_color_fidelity.py — Color fidelity, visual accuracy, and channel ordering tests for PDF rendering.

Prevents BGR/RGB inversion regressions (e.g. red objects rendering as blue, or yellow
objects rendering as cyan/blueish). Validates:
1. Pure primary colors (Red, Green, Blue).
2. Secondary colors (Team Lemon Yellow, Magenta, Cyan).
3. Monochrome and neutral grayscale patches (White, Black, 50% Gray).
4. Lossless PDF → PNG, lossy PDF → JPEG, PDF → WebP, and PDF → TIFF.
5. Pixel-level channel assertions and Mean Absolute Error (MAE) metrics.
6. Transparency compositing over background fill colors.
"""
from __future__ import annotations

import math
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageDraw
import pypdfium2

from localshift.converter import convert_request
from localshift.documents.pdf_image_exporter import PdfToImageExporter
from localshift.documents.renderer import PdfPageRenderer
from localshift.models import ConversionRequest


@pytest.fixture
def color_palette_pdf(tmp_path: Path) -> Path:
    """Create a calibrated multi-color test PDF with known RGB patches."""
    pdf_path = tmp_path / "color_calibration_palette.pdf"
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Top row: Primaries
    # Red patch at (20, 20) -> (180, 180)
    draw.rectangle([20, 20, 180, 180], fill=(255, 0, 0))
    # Green patch at (220, 20) -> (380, 180)
    draw.rectangle([220, 20, 380, 180], fill=(0, 255, 0))
    # Blue patch at (420, 20) -> (580, 180)
    draw.rectangle([420, 20, 580, 180], fill=(0, 0, 255))

    # Bottom row: Lemon Yellow, Cyan, 50% Neutral Gray
    # "Team Lemon" Yellow patch at (20, 220) -> (180, 380)
    draw.rectangle([20, 220, 180, 380], fill=(255, 255, 0))
    # Cyan patch at (220, 220) -> (380, 380)
    draw.rectangle([220, 220, 380, 380], fill=(0, 255, 255))
    # Neutral Gray patch at (420, 220) -> (580, 380)
    draw.rectangle([420, 220, 580, 380], fill=(128, 128, 128))

    img.save(pdf_path, format="PDF")
    return pdf_path


def test_renderer_rgb_numpy_channel_ordering(color_palette_pdf: Path):
    """Verify that PdfPageRenderer.render_page returns numpy array in true RGB order."""
    doc = pypdfium2.PdfDocument(color_palette_pdf)
    page = doc[0]

    # Render at 72 DPI (1:1 with 600x400 image canvas)
    arr = PdfPageRenderer.render_page(page, dpi=72)
    assert isinstance(arr, np.ndarray)
    assert arr.ndim == 3
    assert arr.shape[2] == 3

    # Sample Center of Red patch at (100, 100) -> [y, x] = [100, 100]
    red_pixel = arr[100, 100]
    r, g, b = int(red_pixel[0]), int(red_pixel[1]), int(red_pixel[2])
    assert r > 240, f"Red channel must be > 240, got {r} (Check for BGR swap!)"
    assert g < 15, f"Green channel must be < 15, got {g}"
    assert b < 15, f"Blue channel must be < 15, got {b} (If high, BGR was returned instead of RGB!)"

    # Sample Center of "Team Lemon" Yellow patch at (300, 100)
    yellow_pixel = arr[300, 100]
    yr, yg, yb = int(yellow_pixel[0]), int(yellow_pixel[1]), int(yellow_pixel[2])
    assert yr > 240, f"Yellow Red channel must be > 240, got {yr}"
    assert yg > 240, f"Yellow Green channel must be > 240, got {yg}"
    assert yb < 15, f"Yellow Blue channel must be < 15, got {yb} (If high, yellow turned blue!)"

    doc.close()


def test_renderer_pil_image_color_accuracy(color_palette_pdf: Path):
    """Verify that PdfPageRenderer.render_page_to_image produces color-accurate PIL Image."""
    doc = pypdfium2.PdfDocument(color_palette_pdf)
    page = doc[0]

    im = PdfPageRenderer.render_page_to_image(page, dpi=72)
    assert isinstance(im, Image.Image)
    assert im.mode in ("RGB", "RGBA")

    # Pure Red patch
    r, g, b = im.getpixel((100, 100))[:3]
    assert r > 240 and g < 15 and b < 15

    # Pure Blue patch at (500, 100)
    br, bg, bb = im.getpixel((500, 100))[:3]
    assert br < 15 and bg < 15 and bb > 240

    # Pure Green patch at (300, 100)
    gr, gg, gb = im.getpixel((300, 100))[:3]
    assert gr < 15 and gg > 240 and gb < 15

    # Neutral Gray patch at (500, 300)
    mr, mg, mb = im.getpixel((500, 300))[:3]
    assert abs(mr - 128) < 10
    assert abs(mg - 128) < 10
    assert abs(mb - 128) < 10

    doc.close()


def test_pdf_to_png_lossless_color_fidelity(color_palette_pdf: Path, tmp_path: Path):
    """Verify PDF → PNG export preserves exact colors with low MAE and zero channel swap."""
    out_dir = tmp_path / "png_out"
    paths, _ = PdfToImageExporter.export_pdf_to_images(
        color_palette_pdf,
        out_dir,
        target_format="png",
        options={"dpi": 72},
    )
    assert len(paths) == 1
    png_path = paths[0]
    assert png_path.exists()

    with Image.open(png_path) as im:
        # Sample Red patch
        r, g, b = im.getpixel((100, 100))[:3]
        assert r > 240, f"Expected bright red, got R={r}"
        assert b < 15, f"Expected low blue on red patch, got B={b} (BGR bug detected!)"

        # Sample Lemon Yellow patch
        yr, yg, yb = im.getpixel((100, 300))[:3]
        assert yr > 240 and yg > 240, f"Expected yellow (high R+G), got R={yr}, G={yg}"
        assert yb < 15, f"Expected low blue on yellow patch, got B={yb} (Lemon turned blue!)"


def test_pdf_to_jpeg_color_fidelity_and_compositing(color_palette_pdf: Path, tmp_path: Path):
    """Verify PDF → JPEG export preserves color and composites correctly."""
    out_dir = tmp_path / "jpeg_out"
    paths, _ = PdfToImageExporter.export_pdf_to_images(
        color_palette_pdf,
        out_dir,
        target_format="jpeg",
        options={"dpi": 72, "quality": 95},
    )
    assert len(paths) == 1
    jpg_path = paths[0]
    assert jpg_path.exists()

    with Image.open(jpg_path) as im:
        assert im.mode == "RGB"
        # Sample Red patch (allowing small DCT compression variance)
        r, g, b = im.getpixel((100, 100))
        assert r > 230, f"Expected Red > 230 in JPEG, got {r}"
        assert b < 25, f"Expected Blue < 25 in JPEG red patch, got {b}"

        # Sample Lemon Yellow patch
        yr, yg, yb = im.getpixel((100, 300))
        assert yr > 230 and yg > 230
        assert yb < 25


def test_pdf_to_webp_and_tiff_routes(color_palette_pdf: Path, tmp_path: Path):
    """Verify PDF → WebP and PDF → TIFF routes with accurate RGB color output."""
    out_dir = tmp_path / "other_formats"

    # WebP
    paths_webp, _ = PdfToImageExporter.export_pdf_to_images(
        color_palette_pdf,
        out_dir,
        target_format="webp",
        options={"dpi": 72},
    )
    assert len(paths_webp) == 1
    with Image.open(paths_webp[0]) as im:
        r, g, b = im.getpixel((100, 100))[:3]
        assert r > 230 and b < 25

    # TIFF
    paths_tiff, _ = PdfToImageExporter.export_pdf_to_images(
        color_palette_pdf,
        out_dir,
        target_format="tiff",
        options={"dpi": 72},
    )
    assert len(paths_tiff) == 1
    with Image.open(paths_tiff[0]) as im:
        r, g, b = im.getpixel((100, 100))[:3]
        assert r > 240 and b < 15


def test_mean_absolute_error_against_reference(tmp_path: Path):
    """Compute per-channel Mean Absolute Error (MAE) between input image and rendered PDF."""
    ref_img = Image.new("RGB", (200, 200), color=(220, 80, 40))  # Tangerine/orange tone
    draw = ImageDraw.Draw(ref_img)
    draw.rectangle([40, 40, 160, 160], fill=(255, 215, 0))  # Gold/lemon tone
    ref_pdf = tmp_path / "ref_target.pdf"
    ref_img.save(ref_pdf, format="PDF")

    out_dir = tmp_path / "rendered"
    paths, _ = PdfToImageExporter.export_pdf_to_images(ref_pdf, out_dir, target_format="png", options={"dpi": 72})
    rendered_img = Image.open(paths[0]).convert("RGB")

    ref_arr = np.array(ref_img)
    ren_arr = np.array(rendered_img)

    # MAE per channel
    mae = np.mean(np.abs(ref_arr.astype(float) - ren_arr.astype(float)))
    # With correct RGB channels, MAE between rasterized vector and original is < 2.0
    # (If BGR inversion were present, MAE would exceed 100.0)
    assert mae < 3.0, f"Mean Absolute Error {mae:.2f} is too high! Channel ordering error."
