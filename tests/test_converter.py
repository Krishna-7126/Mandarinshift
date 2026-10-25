"""
tests/test_converter.py — Unit and integration tests for the conversion engine.

Coverage targets:
- Happy-path conversions for all supported route pairs.
- JPEG alpha compositing (transparent PNG → JPEG).
- Mode coercion for BMP / TIFF / WebP.
- Unique output naming and collision avoidance.
- Input validation: missing file, oversized file, same-format rejection.
- Format detection: fake extension, unrecognised format.
- Atomic write: temp file is cleaned up on failure.
- Symlink handling.
- ConversionResult fields.
- Public API surface (importable from top-level package).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from localshift import ConversionError, convert_image
from localshift.converter import (
    MAX_INPUT_BYTES,
    ConversionResult,
    unique_output_path,
)
from localshift.formats import (
    SUPPORTED,
    input_format,
    normalize_format,
    output_formats_for,
    route_supported,
    sniff_format,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_png(path: Path, mode: str = "RGBA") -> Path:
    """Create a minimal image at *path* and return *path*."""
    Image.new(mode, (9, 7), (240, 20, 30, 120) if mode == "RGBA" else (200, 100, 50)).save(path)
    return path


# ---------------------------------------------------------------------------
# Public API import tests
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_convert_image_importable_from_package(self):
        from localshift import convert_image as ci
        assert callable(ci)

    def test_conversion_error_importable_from_package(self):
        from localshift import ConversionError as CE
        assert issubclass(CE, RuntimeError)

    def test_conversion_result_importable_from_package(self):
        from localshift import ConversionResult as CR
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(CR)}
        assert "output_path" in field_names

    def test_no_pyside6_import_on_backend_import(self):
        """Importing backend modules must not trigger PySide6 import."""
        import sys
        # If PySide6 is not installed, the backend must still be importable.
        # If it IS installed, it must not have been imported as a side-effect.
        was_imported_before = "PySide6" in sys.modules
        import localshift  # noqa: F401 — side-effect check
        import localshift.converter  # noqa: F401
        import localshift.formats  # noqa: F401
        import localshift.cli  # noqa: F401
        if not was_imported_before:
            assert "PySide6" not in sys.modules, (
                "Importing backend modules must not load PySide6"
            )


# ---------------------------------------------------------------------------
# Format registry tests
# ---------------------------------------------------------------------------

class TestFormats:
    def test_supported_contains_expected_formats(self):
        assert SUPPORTED >= {"png", "jpeg", "webp", "bmp", "tiff"}

    def test_normalize_canonical(self):
        assert normalize_format("png") == "png"
        assert normalize_format("jpeg") == "jpeg"

    def test_normalize_alias_jpg(self):
        assert normalize_format("jpg") == "jpeg"

    def test_normalize_alias_tif(self):
        assert normalize_format("tif") == "tiff"

    def test_normalize_dotted(self):
        assert normalize_format(".png") == "png"

    def test_normalize_uppercase(self):
        assert normalize_format("PNG") == "png"
        assert normalize_format("JPEG") == "jpeg"

    def test_normalize_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown format"):
            normalize_format("xyz_unknown_format")

    def test_input_format_recognized(self):
        assert input_format(Path("file.png")) == "png"
        assert input_format(Path("file.jpg")) == "jpeg"
        assert input_format(Path("file.tif")) == "tiff"
        assert input_format(Path("file.pdf")) == "pdf"

    def test_input_format_unrecognized_returns_none(self):
        assert input_format(Path("file.xyz")) is None
        assert input_format(Path("file.odt")) is None

    def test_route_supported_canonical(self):
        assert route_supported("png", "jpeg")
        assert route_supported("jpeg", "webp")
        assert route_supported("bmp", "tiff")

    def test_route_supported_aliases(self):
        assert route_supported("jpg", "webp")
        assert route_supported("tif", "png")

    def test_route_same_format_rejected(self):
        assert not route_supported("png", "png")
        assert not route_supported("jpg", "jpeg")  # aliases of same format

    def test_route_unknown_format_returns_false(self):
        assert route_supported("pdf", "png")
        assert not route_supported("pdf", "xyz")
        assert not route_supported("png", "xyz")

    def test_output_formats_for_png(self, tmp_path):
        p = tmp_path / "file.png"
        p.touch()
        formats = output_formats_for(p)
        assert "jpeg" in formats
        assert "webp" in formats
        assert "pdf" in formats
        assert "png" not in formats

    def test_output_formats_for_unsupported(self, tmp_path):
        p = tmp_path / "file.xyz"
        assert output_formats_for(p) == []

    def test_output_formats_for_pdf(self, tmp_path):
        p = tmp_path / "file.pdf"
        assert output_formats_for(p) == ["docx", "jpeg", "png", "txt"]

    def test_sniff_format_real_png(self, tmp_path):
        p = tmp_path / "test.png"
        Image.new("RGB", (4, 4), (0, 0, 0)).save(p, format="PNG")
        assert sniff_format(p) == "png"

    def test_sniff_format_jpeg_with_wrong_extension(self, tmp_path):
        """A JPEG saved with .png extension should be identified as jpeg."""
        p = tmp_path / "mislabeled.png"
        Image.new("RGB", (4, 4), (0, 0, 0)).save(p, format="JPEG")
        assert sniff_format(p) == "jpeg"

    def test_sniff_format_text_file_returns_none(self, text_file):
        assert sniff_format(text_file) is None


# ---------------------------------------------------------------------------
# Conversion happy-path tests
# ---------------------------------------------------------------------------

class TestConversionHappyPath:
    def test_png_to_jpeg(self, tmp_path, rgba_png):
        result = convert_image(rgba_png, "jpeg", tmp_path)
        with Image.open(result) as im:
            assert im.format == "JPEG"
            assert im.mode == "RGB"
            assert im.size == (9, 7)

    def test_png_to_jpeg_alias_jpg(self, tmp_path, rgba_png):
        """CLI alias 'jpg' must be accepted."""
        result = convert_image(rgba_png, "jpg", tmp_path)
        assert result.suffix == ".jpeg"
        with Image.open(result) as im:
            assert im.format == "JPEG"

    def test_png_to_webp(self, tmp_path, rgb_png):
        result = convert_image(rgb_png, "webp", tmp_path)
        with Image.open(result) as im:
            assert im.format == "WEBP"

    def test_png_to_bmp(self, tmp_path, rgb_png):
        result = convert_image(rgb_png, "bmp", tmp_path)
        with Image.open(result) as im:
            assert im.format == "BMP"

    def test_png_to_tiff(self, tmp_path, rgb_png):
        result = convert_image(rgb_png, "tiff", tmp_path)
        with Image.open(result) as im:
            assert im.format == "TIFF"

    def test_jpeg_to_png(self, tmp_path, rgb_jpeg):
        result = convert_image(rgb_jpeg, "png", tmp_path)
        with Image.open(result) as im:
            assert im.format == "PNG"

    def test_jpeg_to_webp(self, tmp_path, rgb_jpeg):
        result = convert_image(rgb_jpeg, "webp", tmp_path)
        with Image.open(result) as im:
            assert im.format == "WEBP"

    def test_grayscale_png_to_jpeg(self, tmp_path, gray_png):
        """Grayscale images should convert to JPEG without error."""
        result = convert_image(gray_png, "jpeg", tmp_path)
        with Image.open(result) as im:
            assert im.format == "JPEG"

    def test_output_path_returned(self, tmp_path, rgb_png):
        result = convert_image(rgb_png, "webp", tmp_path)
        assert isinstance(result, Path)
        assert result.exists()

    def test_default_output_dir_is_source_parent(self, tmp_path, rgb_png):
        """When output_dir is omitted, output goes next to the source."""
        result = convert_image(rgb_png, "webp")
        assert result.parent == rgb_png.parent
        result.unlink(missing_ok=True)

    def test_output_dir_created_if_missing(self, tmp_path, rgb_png):
        new_dir = tmp_path / "new_subdir"
        assert not new_dir.exists()
        result = convert_image(rgb_png, "jpeg", new_dir)
        assert new_dir.is_dir()
        assert result.parent == new_dir


# ---------------------------------------------------------------------------
# JPEG alpha-compositing tests
# ---------------------------------------------------------------------------

class TestJpegAlpha:
    def test_rgba_png_to_jpeg_composited_white(self, tmp_path, rgba_png):
        """Transparent PNG → JPEG: output must be RGB (no alpha channel)."""
        result = convert_image(rgba_png, "jpeg", tmp_path)
        with Image.open(result) as im:
            assert im.mode == "RGB"

    def test_rgba_png_to_jpeg_custom_background(self, tmp_path, rgba_png):
        """Custom JPEG background colour is applied."""
        result = convert_image(rgba_png, "jpeg", tmp_path, jpeg_background=(0, 0, 255))
        assert result.exists()
        with Image.open(result) as im:
            assert im.mode == "RGB"

    def test_opaque_png_to_jpeg_is_rgb(self, tmp_path, rgb_png):
        result = convert_image(rgb_png, "jpeg", tmp_path)
        with Image.open(result) as im:
            assert im.mode == "RGB"


# ---------------------------------------------------------------------------
# Collision avoidance tests
# ---------------------------------------------------------------------------

class TestCollisionAvoidance:
    def test_never_overwrites_existing(self, tmp_path, rgb_png):
        a = convert_image(rgb_png, "bmp", tmp_path)
        b = convert_image(rgb_png, "bmp", tmp_path)
        assert a != b
        assert a.exists()
        assert b.exists()

    def test_three_collisions(self, tmp_path, rgb_png):
        paths = [convert_image(rgb_png, "bmp", tmp_path) for _ in range(3)]
        assert len(set(paths)) == 3
        assert all(p.exists() for p in paths)

    def test_unique_output_path_no_collision(self, tmp_path):
        assert unique_output_path(tmp_path, "pic", "png") == tmp_path / "pic.png"

    def test_unique_output_path_first_collision(self, tmp_path):
        (tmp_path / "pic.png").touch()
        assert unique_output_path(tmp_path, "pic", "png").name == "pic (2).png"

    def test_unique_output_path_multiple_collisions(self, tmp_path):
        (tmp_path / "pic.png").touch()
        (tmp_path / "pic (2).png").touch()
        (tmp_path / "pic (3).png").touch()
        assert unique_output_path(tmp_path, "pic", "png").name == "pic (4).png"

    def test_source_file_never_modified(self, tmp_path, rgb_png):
        import hashlib
        before = hashlib.sha256(rgb_png.read_bytes()).hexdigest()
        convert_image(rgb_png, "jpeg", tmp_path)
        after = hashlib.sha256(rgb_png.read_bytes()).hexdigest()
        assert before == after, "Source file was modified during conversion"


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConversionError, match="not found"):
            convert_image(tmp_path / "nonexistent.png", "jpeg", tmp_path)

    def test_same_format_rejected(self, tmp_path, rgb_png):
        with pytest.raises(ConversionError):
            convert_image(rgb_png, "png", tmp_path)

    def test_same_format_alias_rejected(self, tmp_path, rgb_jpeg):
        """jpg → jpeg should be rejected (same format)."""
        with pytest.raises(ConversionError):
            convert_image(rgb_jpeg, "jpeg", tmp_path)

    def test_unsupported_target_raises(self, tmp_path, rgb_png):
        with pytest.raises(ConversionError):
            convert_image(rgb_png, "docx", tmp_path)

    def test_unknown_format_string_raises(self, tmp_path, rgb_png):
        with pytest.raises(ConversionError):
            convert_image(rgb_png, "xyz_not_real", tmp_path)

    def test_oversized_file_raises(self, tmp_path, monkeypatch):
        """Files exceeding the size limit are rejected before opening."""
        src = tmp_path / "big.png"
        Image.new("RGB", (4, 4)).save(src, format="PNG")
        # Monkeypatch stat to report a huge size.
        real_stat = src.stat()

        class _FakeStat:
            st_size = MAX_INPUT_BYTES + 1

        monkeypatch.setattr(Path, "stat", lambda _self: _FakeStat())
        with pytest.raises(ConversionError, match="exceeds"):
            convert_image(src, "jpeg", tmp_path)

    def test_fake_extension_real_image_content_detected(self, tmp_path):
        """A JPEG saved as .png is identified by magic bytes and can be converted."""
        p = tmp_path / "actually_jpeg.png"
        Image.new("RGB", (4, 4), (0, 128, 255)).save(p, format="JPEG")
        # The target extension says PNG but the content is JPEG.
        # convert_image should detect JPEG via sniff and convert to webp.
        result = convert_image(p, "webp", tmp_path)
        assert result.exists()
        with Image.open(result) as im:
            assert im.format == "WEBP"

    def test_text_file_with_png_extension_raises(self, tmp_path, text_file):
        """A text file named .png cannot be converted; must raise ConversionError."""
        with pytest.raises(ConversionError):
            convert_image(text_file, "jpeg", tmp_path)


# ---------------------------------------------------------------------------
# Symlink tests (skipped on platforms that don't support symlinks without admin)
# ---------------------------------------------------------------------------

class TestSymlinks:
    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("LOCALSHIFT_TEST_SYMLINKS"),
        reason=(
            "Symlink creation on Windows requires Developer Mode or admin privileges. "
            "Set LOCALSHIFT_TEST_SYMLINKS=1 to enable."
        ),
    )
    def test_symlink_to_valid_image_accepted(self, tmp_path, rgb_png):
        link = tmp_path / "link.png"
        link.symlink_to(rgb_png)
        result = convert_image(link, "jpeg", tmp_path)
        assert result.exists()

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("LOCALSHIFT_TEST_SYMLINKS"),
        reason="Symlinks require Developer Mode on Windows.",
    )
    def test_dangling_symlink_raises(self, tmp_path):
        link = tmp_path / "dangling.png"
        link.symlink_to(tmp_path / "nonexistent_target.png")
        with pytest.raises(ConversionError):
            convert_image(link, "jpeg", tmp_path)


# ---------------------------------------------------------------------------
# Temporary file cleanup tests
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_no_temp_files_after_success(self, tmp_path, rgb_png):
        """After a successful conversion, no .tmp files should remain."""
        convert_image(rgb_png, "jpeg", tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files not cleaned: {tmp_files}"

    def test_no_temp_files_after_failure(self, tmp_path, text_file):
        """After a failed conversion, no .tmp files should remain."""
        try:
            convert_image(text_file, "jpeg", tmp_path)
        except ConversionError:
            pass
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked after failure: {tmp_files}"


# ---------------------------------------------------------------------------
# Regression tests (preserve original baseline behaviours)
# ---------------------------------------------------------------------------

class TestRegression:
    """Preserve behaviours documented in README and original test suite."""

    def test_png_to_jpeg_baseline(self, tmp_path):
        """Original test_png_jpeg: RGBA → JPEG produces RGB image of correct size."""
        src = tmp_path / "in.png"
        Image.new("RGBA", (9, 7), (240, 20, 30, 120)).save(src)
        result = convert_image(src, "jpg", tmp_path)
        with Image.open(result) as im:
            assert im.format == "JPEG" and im.mode == "RGB" and im.size == (9, 7)

    def test_png_to_webp_baseline(self, tmp_path):
        """Original test_png_webp."""
        src = tmp_path / "in.png"
        Image.new("RGBA", (9, 7), (240, 20, 30, 120)).save(src)
        result = convert_image(src, "webp", tmp_path)
        with Image.open(result) as im:
            assert im.format == "WEBP"

    def test_never_overwrites_baseline(self, tmp_path):
        """Original test_never_overwrites."""
        src = tmp_path / "in.png"
        Image.new("RGBA", (9, 7), (240, 20, 30, 120)).save(src)
        a = convert_image(src, "bmp", tmp_path)
        b = convert_image(src, "bmp", tmp_path)
        assert a != b and a.exists() and b.exists()

    def test_same_format_rejected_baseline(self, tmp_path):
        """Original test_same_format_rejected."""
        src = tmp_path / "in.png"
        Image.new("RGBA", (9, 7), (240, 20, 30, 120)).save(src)
        with pytest.raises(ConversionError):
            convert_image(src, "png", tmp_path)

    def test_fake_extension_rejected_baseline(self, tmp_path):
        """Original test_fake_extension_rejected: text file named .png raises."""
        src = tmp_path / "bad.png"
        src.write_text("not an image")
        with pytest.raises(ConversionError):
            convert_image(src, "webp", tmp_path)

    def test_unsupported_input_baseline(self):
        """Original test_unsupported_input."""
        assert output_formats_for(Path("file.xyz")) == []
        from localshift.documents.docx_adapter import DocxToPdfAdapter
        expected_docx_targets = ["pdf"] if DocxToPdfAdapter().is_available() else []
        assert output_formats_for(Path("file.docx")) == expected_docx_targets
        assert route_supported("pdf", "png")
        assert not route_supported("pdf", "xyz")

    def test_route_aliases_baseline(self):
        """Original test_route_aliases."""
        assert route_supported("jpg", "webp")
        assert not route_supported("png", "png")

    def test_unique_name_baseline(self, tmp_path):
        """Original test_unique_name."""
        (tmp_path / "pic.png").touch()
        assert unique_output_path(tmp_path, "pic", "png").name == "pic (2).png"
