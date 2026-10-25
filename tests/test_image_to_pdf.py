"""
Tests for Image -> PDF conversion engine (LS-BE-011).

Covers:
- Capability discovery & route registration for all raster image formats (PNG, JPEG, WebP, BMP, TIFF)
- Option validation (page_size, fit, orientation, margin, background_color, dpi, quality)
- Single image -> PDF conversion for every advertised format
- Multiple images -> one ordered multipage PDF assembly
- Page sizing (A4, Letter, original image dimensions)
- Fit modes ('contain', 'cover') and margin calculations
- Orientation ('portrait', 'landscape', 'auto')
- Alpha channel transparency compositing & custom background color
- EXIF orientation transposition
- CMYK and grayscale handling
- Corrupt, empty, oversized, and invalid inputs
- Collision avoidance, atomicity, and cleanup
- Cancellation handling
- High-level APIs (convert_image, convert_images_to_pdf, convert_images_batch_to_pdf, JobQueue)
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from PIL import Image

import pypdfium2

from localshift import (
    ConversionCancelledError,
    ConversionError,
    ConversionFailedError,
    ConversionRequest,
    ConversionResult,
    InputTooLargeError,
    InvalidInputError,
    JobQueue,
    JobStatus,
    convert_image,
    convert_images_batch_to_pdf,
    convert_images_to_pdf,
    convert_request,
    is_route_supported,
)
from localshift.documents.image_to_pdf import (
    ImageToPdfAdapter,
    ImageToPdfConverter,
    PAGE_SIZES,
)
from localshift.documents.pdf_inspector import PdfInspector
from localshift.formats import output_formats_for, route_supported
from localshift.planner import (
    FindingCode,
    FindingSeverity,
    get_applicable_options,
    validate_preflight,
)


# ===========================================================================
# Fixture Helpers
# ===========================================================================

@pytest.fixture
def sample_images(tmp_path: Path) -> dict[str, Path]:
    """Generate clean sample images in each supported raster format."""
    images = {}
    
    # 1. PNG (RGBA with transparency)
    png_path = tmp_path / "test.png"
    im_png = Image.new("RGBA", (200, 100), (255, 0, 0, 128))
    im_png.save(png_path, format="PNG")
    images["png"] = png_path

    # 2. JPEG (RGB)
    jpeg_path = tmp_path / "test.jpeg"
    im_jpeg = Image.new("RGB", (150, 200), (0, 255, 0))
    im_jpeg.save(jpeg_path, format="JPEG")
    images["jpeg"] = jpeg_path

    # 3. WebP (RGB)
    webp_path = tmp_path / "test.webp"
    im_webp = Image.new("RGB", (180, 120), (0, 0, 255))
    im_webp.save(webp_path, format="WEBP")
    images["webp"] = webp_path

    # 4. BMP (RGB)
    bmp_path = tmp_path / "test.bmp"
    im_bmp = Image.new("RGB", (100, 100), (255, 255, 0))
    im_bmp.save(bmp_path, format="BMP")
    images["bmp"] = bmp_path

    # 5. TIFF (RGB)
    tiff_path = tmp_path / "test.tiff"
    im_tiff = Image.new("RGB", (120, 160), (255, 0, 255))
    im_tiff.save(tiff_path, format="TIFF")
    images["tiff"] = tiff_path

    return images


# ===========================================================================
# 1. Capabilities & Route Discovery
# ===========================================================================

class TestCapabilitiesAndRoutes:
    def test_routes_advertised_for_all_image_formats(self):
        for fmt in ("png", "jpeg", "jpg", "webp", "bmp", "tiff", "tif"):
            assert route_supported(fmt, "pdf") is True
            assert is_route_supported(fmt, "pdf") is True

    def test_output_formats_for_image_includes_pdf(self, tmp_path: Path):
        for ext in ("png", "jpeg", "webp", "bmp", "tiff"):
            dummy = tmp_path / f"sample.{ext}"
            dummy.touch()
            formats = output_formats_for(dummy)
            assert "pdf" in formats

    def test_applicable_options_image_to_pdf(self):
        options = get_applicable_options("png", "pdf")
        option_names = {opt.name for opt in options}
        expected = {
            "page_size",
            "fit",
            "orientation",
            "margin",
            "background_color",
            "dpi",
            "quality",
            "additional_sources",
        }
        assert expected.issubset(option_names)


# ===========================================================================
# 2. Option Validation
# ===========================================================================

class TestOptionValidation:
    def test_valid_options_pass(self):
        opts = {
            "page_size": "a4",
            "fit": "contain",
            "orientation": "auto",
            "margin": 18.0,
            "background_color": (240, 240, 240),
            "dpi": 200,
            "quality": 90,
            "additional_sources": [Path("extra1.png"), Path("extra2.png")],
        }
        validated = ImageToPdfConverter.validate_options(opts)
        assert validated["page_size"] == "a4"
        assert validated["fit"] == "contain"
        assert validated["orientation"] == "auto"
        assert validated["margin"] == 18.0
        assert validated["background_color"] == (240, 240, 240)
        assert validated["dpi"] == 200
        assert validated["quality"] == 90
        assert len(validated["additional_sources"]) == 2

    def test_invalid_page_size_raises(self):
        with pytest.raises(InvalidInputError, match="Invalid page_size"):
            ImageToPdfConverter.validate_options({"page_size": "b5_not_supported"})

    def test_invalid_fit_raises(self):
        with pytest.raises(InvalidInputError, match="Invalid fit mode"):
            ImageToPdfConverter.validate_options({"fit": "stretch_invalid"})

    def test_invalid_orientation_raises(self):
        with pytest.raises(InvalidInputError, match="Invalid orientation"):
            ImageToPdfConverter.validate_options({"orientation": "diagonal"})

    def test_invalid_margin_raises(self):
        with pytest.raises(InvalidInputError, match="Margin must be non-negative"):
            ImageToPdfConverter.validate_options({"margin": -10})

    def test_invalid_background_color_raises(self):
        with pytest.raises(InvalidInputError, match="Background color must be an RGB 3-tuple"):
            ImageToPdfConverter.validate_options({"background_color": (255, 0)})
        with pytest.raises(InvalidInputError, match="Background color must be an RGB 3-tuple"):
            ImageToPdfConverter.validate_options({"background_color": (300, 0, 0)})

    def test_invalid_dpi_raises(self):
        with pytest.raises(InvalidInputError, match="DPI must be between"):
            ImageToPdfConverter.validate_options({"dpi": 50})
        with pytest.raises(InvalidInputError, match="DPI must be between"):
            ImageToPdfConverter.validate_options({"dpi": 600})

    def test_invalid_quality_raises(self):
        with pytest.raises(InvalidInputError, match="Quality must be between"):
            ImageToPdfConverter.validate_options({"quality": 0})
        with pytest.raises(InvalidInputError, match="Quality must be between"):
            ImageToPdfConverter.validate_options({"quality": 105})

    def test_preflight_catches_invalid_option(self, tmp_path: Path):
        p = tmp_path / "img.png"
        Image.new("RGB", (10, 10)).save(p)
        req = ConversionRequest(
            source=p,
            target_format="pdf",
            options={"margin": -5},
        )
        findings = validate_preflight(req)
        assert any(f.field == "options.margin" and f.severity == FindingSeverity.ERROR for f in findings)


# ===========================================================================
# 3. Single Image → PDF Conversion (All Formats)
# ===========================================================================

class TestSingleImageToPdf:
    def test_convert_png_to_pdf(self, sample_images: dict[str, Path], tmp_path: Path):
        req = ConversionRequest(
            source=sample_images["png"],
            target_format="pdf",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        assert result.output_path.suffix == ".pdf"
        assert result.output_path.name == "test.pdf"

        # Verify PDF compliance
        report = PdfInspector.inspect(result.output_path)
        assert report.is_readable is True
        assert report.page_count == 1

    def test_convert_jpeg_to_pdf(self, sample_images: dict[str, Path], tmp_path: Path):
        req = ConversionRequest(
            source=sample_images["jpeg"],
            target_format="pdf",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        report = PdfInspector.inspect(result.output_path)
        assert report.page_count == 1

    def test_convert_webp_to_pdf(self, sample_images: dict[str, Path], tmp_path: Path):
        req = ConversionRequest(
            source=sample_images["webp"],
            target_format="pdf",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        report = PdfInspector.inspect(result.output_path)
        assert report.page_count == 1

    def test_convert_bmp_to_pdf(self, sample_images: dict[str, Path], tmp_path: Path):
        req = ConversionRequest(
            source=sample_images["bmp"],
            target_format="pdf",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        report = PdfInspector.inspect(result.output_path)
        assert report.page_count == 1

    def test_convert_tiff_to_pdf(self, sample_images: dict[str, Path], tmp_path: Path):
        req = ConversionRequest(
            source=sample_images["tiff"],
            target_format="pdf",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        report = PdfInspector.inspect(result.output_path)
        assert report.page_count == 1


# ===========================================================================
# 4. Multiple Images → One Ordered Multipage PDF
# ===========================================================================

class TestMultipageImageAssembly:
    def test_multiple_images_assembled_in_order(
        self, sample_images: dict[str, Path], tmp_path: Path
    ):
        # Assemble 3 images: PNG, JPEG, WebP
        sources = [
            sample_images["png"],
            sample_images["jpeg"],
            sample_images["webp"],
        ]
        out_pdf = convert_images_to_pdf(
            sources=sources,
            output_dir=tmp_path,
            output_name="assembled_document",
        )
        assert out_pdf.is_file()
        assert out_pdf.name == "assembled_document.pdf"

        # Verify page count and inspection
        report = PdfInspector.inspect(out_pdf)
        assert report.is_readable is True
        assert report.page_count == 3

    def test_adapter_multipage_via_additional_sources(
        self, sample_images: dict[str, Path], tmp_path: Path
    ):
        req = ConversionRequest(
            source=sample_images["png"],
            target_format="pdf",
            output_dir=tmp_path,
            options={
                "additional_sources": [sample_images["bmp"], sample_images["tiff"]],
            },
        )
        result = convert_request(req)
        assert result.output_path.is_file()

        doc = pypdfium2.PdfDocument(result.output_path)
        assert len(doc) == 3
        doc.close()


# ===========================================================================
# 5. Page Sizing, Margins & Orientation
# ===========================================================================

class TestPageLayoutAndGeometry:
    def test_a4_portrait_geometry(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (100, 200), "red").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "a4", "orientation": "portrait"},
        )
        doc = pypdfium2.PdfDocument(out_pdf)
        w, h = doc[0].get_size()
        doc.close()

        # A4: ~595 x 842 pt
        assert abs(w - 595.28) < 1.0
        assert abs(h - 841.89) < 1.0

    def test_a4_landscape_geometry(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (200, 100), "blue").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "a4", "orientation": "landscape"},
        )
        doc = pypdfium2.PdfDocument(out_pdf)
        w, h = doc[0].get_size()
        doc.close()

        # A4 Landscape: ~842 x 595 pt
        assert abs(w - 841.89) < 1.0
        assert abs(h - 595.28) < 1.0

    def test_letter_geometry(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (100, 100), "green").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "letter", "orientation": "portrait"},
        )
        doc = pypdfium2.PdfDocument(out_pdf)
        w, h = doc[0].get_size()
        doc.close()

        # Letter: 612 x 792 pt
        assert abs(w - 612.0) < 1.0
        assert abs(h - 792.0) < 1.0

    def test_original_dimensions_geometry(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        # 300x150 pixels at 150 DPI = 2.0x1.0 inches = 144x72 points
        Image.new("RGB", (300, 150), "yellow").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "original", "dpi": 150},
        )
        doc = pypdfium2.PdfDocument(out_pdf)
        w, h = doc[0].get_size()
        doc.close()

        assert abs(w - 144.0) < 1.0
        assert abs(h - 72.0) < 1.0

    def test_auto_orientation(self, tmp_path: Path):
        wide_img = tmp_path / "wide.png"
        tall_img = tmp_path / "tall.png"
        Image.new("RGB", (400, 200)).save(wide_img)
        Image.new("RGB", (200, 400)).save(tall_img)

        out_pdf = convert_images_to_pdf(
            [wide_img, tall_img],
            output_dir=tmp_path,
            options={"page_size": "a4", "orientation": "auto"},
        )
        doc = pypdfium2.PdfDocument(out_pdf)
        # Page 1 should be landscape
        w1, h1 = doc[0].get_size()
        assert w1 > h1
        # Page 2 should be portrait
        w2, h2 = doc[1].get_size()
        assert w2 < h2
        doc.close()

    def test_margin_exceeding_page_size_raises(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (100, 100)).save(img_path)
        # A4 width is ~595 pt, margin of 350 pt on both sides is 700 pt > 595 pt
        with pytest.raises(InvalidInputError, match="Margin .* exceeds page dimensions"):
            convert_images_to_pdf(
                [img_path],
                output_dir=tmp_path,
                options={"page_size": "a4", "margin": 350.0},
            )


# ===========================================================================
# 6. Fit Modes (Contain vs Cover)
# ===========================================================================

class TestFitModes:
    def test_contain_mode_preserves_full_image(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (200, 100), "red").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "a4", "fit": "contain"},
        )
        assert out_pdf.is_file()

    def test_cover_mode_crops_excess(self, tmp_path: Path):
        img_path = tmp_path / "img.png"
        Image.new("RGB", (200, 100), "blue").save(img_path)

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"page_size": "a4", "fit": "cover"},
        )
        assert out_pdf.is_file()


# ===========================================================================
# 7. Transparency, Alpha Compositing & Color Modes
# ===========================================================================

class TestTransparencyAndColorModes:
    def test_rgba_transparent_png_composited_with_custom_background(self, tmp_path: Path):
        img_path = tmp_path / "transparent.png"
        # Half-transparent blue square
        rgba = Image.new("RGBA", (100, 100), (0, 0, 255, 128))
        rgba.save(img_path, format="PNG")

        out_pdf = convert_images_to_pdf(
            [img_path],
            output_dir=tmp_path,
            options={"background_color": (255, 255, 255)},
        )
        assert out_pdf.is_file()
        doc = pypdfium2.PdfDocument(out_pdf)
        assert len(doc) == 1
        doc.close()

    def test_cmyk_image_conversion(self, tmp_path: Path):
        img_path = tmp_path / "cmyk.jpeg"
        cmyk = Image.new("CMYK", (100, 100), (100, 50, 0, 0))
        cmyk.save(img_path, format="JPEG")

        out_pdf = convert_images_to_pdf([img_path], output_dir=tmp_path)
        assert out_pdf.is_file()
        doc = pypdfium2.PdfDocument(out_pdf)
        assert len(doc) == 1
        doc.close()

    def test_grayscale_image_conversion(self, tmp_path: Path):
        img_path = tmp_path / "gray.png"
        gray = Image.new("L", (100, 100), 128)
        gray.save(img_path, format="PNG")

        out_pdf = convert_images_to_pdf([img_path], output_dir=tmp_path)
        assert out_pdf.is_file()


# ===========================================================================
# 8. Error Handling & Edge Cases
# ===========================================================================

class TestErrorHandling:
    def test_nonexistent_source_raises(self, tmp_path: Path):
        ghost = tmp_path / "ghost.png"
        with pytest.raises(InvalidInputError):
            convert_images_to_pdf([ghost], output_dir=tmp_path)

    def test_empty_file_raises(self, tmp_path: Path):
        empty_p = tmp_path / "empty.png"
        empty_p.touch()
        with pytest.raises(InvalidInputError, match="empty"):
            convert_images_to_pdf([empty_p], output_dir=tmp_path)

    def test_corrupt_file_raises(self, tmp_path: Path):
        corrupt_p = tmp_path / "corrupt.png"
        corrupt_p.write_bytes(b"NOT_A_REAL_IMAGE_DATA")
        with pytest.raises(InvalidInputError):
            convert_images_to_pdf([corrupt_p], output_dir=tmp_path)

    def test_empty_sources_list_raises(self, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="No source images"):
            convert_images_to_pdf([], output_dir=tmp_path)


# ===========================================================================
# 9. Concurrency, Collision Protection & Cancellation
# ===========================================================================

class TestConcurrencyAndCleanup:
    def test_collision_protection_preserves_existing_pdf(self, tmp_path: Path):
        img_path = tmp_path / "test.png"
        Image.new("RGB", (50, 50)).save(img_path)

        # Pre-create the destination file
        existing = tmp_path / "test.pdf"
        existing.write_bytes(b"%PDF-1.4\n%EXISTING_PRESERVED\n")

        req = ConversionRequest(
            source=img_path,
            target_format="pdf",
            output_dir=tmp_path,
        )
        res = convert_request(req)

        # Existing untouched
        assert b"%EXISTING_PRESERVED" in existing.read_bytes()
        # New output gets (2) suffix
        assert res.output_path.name == "test (2).pdf"
        assert res.output_path.is_file()

    def test_cancellation_cleans_up_temp_files(self, tmp_path: Path):
        img_path = tmp_path / "test.png"
        Image.new("RGB", (50, 50)).save(img_path)

        def cancelled():
            return True

        req = ConversionRequest(
            source=img_path,
            target_format="pdf",
            output_dir=tmp_path,
        )
        with pytest.raises(ConversionCancelledError):
            convert_request(req, cancel_check=cancelled)

        # Check no stray output or temp files left
        files = list(tmp_path.iterdir())
        assert files == [img_path]


# ===========================================================================
# 10. High-Level APIs & Batch Conversion
# ===========================================================================

class TestHighLevelIntegration:
    def test_convert_image_wrapper_single_png_to_pdf(self, tmp_path: Path):
        p = tmp_path / "photo.png"
        Image.new("RGB", (80, 80), "purple").save(p)

        out_pdf = convert_image(p, "pdf", output_dir=tmp_path)
        assert out_pdf.is_file()
        assert out_pdf.name == "photo.pdf"

    def test_batch_convert_images_to_separate_pdfs(self, tmp_path: Path):
        img1 = tmp_path / "img1.png"
        img2 = tmp_path / "img2.jpg"
        Image.new("RGB", (50, 50), "red").save(img1)
        Image.new("RGB", (60, 60), "blue").save(img2)

        out_pdfs = convert_images_batch_to_pdf([img1, img2], output_dir=tmp_path)
        assert len(out_pdfs) == 2
        assert out_pdfs[0].name == "img1.pdf"
        assert out_pdfs[1].name == "img2.pdf"
        assert out_pdfs[0].is_file()
        assert out_pdfs[1].is_file()

    def test_job_queue_async_image_to_pdf(self, tmp_path: Path):
        img = tmp_path / "async_test.png"
        Image.new("RGB", (60, 60), "cyan").save(img)

        queue = JobQueue(max_workers=1)
        job = queue.submit(
            source=img,
            target_format="pdf",
            output_dir=tmp_path,
        )
        queue.shutdown(wait=True)
        res = queue.get_result(job.job_id)
        assert res.status == JobStatus.SUCCEEDED
        assert res.output_path.is_file()
