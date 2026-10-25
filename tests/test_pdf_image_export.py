"""
Tests for PDF -> PNG and PDF -> JPEG conversion engine (LS-BE-010).

Covers:
- Capability discovery & route registration
- Page selection syntax and parsing (all, single, ranges, lists, bounds)
- Option validation (DPI, quality, pattern safety, jpeg_background)
- Single-page PDF export (PNG & JPEG, headers, DPI scaling)
- Multipage PDF batch export (all pages, subsets, naming, output_paths)
- Custom output patterns with token substitution
- Atomic placement, collision avoidance, and cleanup on failure
- Cancellation handling
- Encrypted, corrupted, empty, and invalid PDF handling
- High-level API integration (convert_image, JobQueue)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest
from PIL import Image

from localshift import (
    ConversionCancelledError,
    ConversionFailedError,
    ConversionRequest,
    ConversionResult,
    InvalidInputError,
    JobQueue,
    JobStatus,
    convert_image,
    convert_request,
    default_registry,
    is_route_supported,
)
from localshift.documents.pdf_image_exporter import (
    PdfToImageExporter,
    parse_page_selection,
    validate_options,
)
from localshift.formats import output_formats_for, route_supported
from localshift.planner import (
    FindingCode,
    FindingSeverity,
    get_applicable_options,
    plan_conversion,
    validate_preflight,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "documents"


# ===========================================================================
# 1. Capabilities & Route Discovery
# ===========================================================================

class TestCapabilitiesAndRoutes:
    def test_routes_advertised(self):
        assert route_supported("pdf", "png") is True
        assert route_supported("pdf", "jpeg") is True
        assert route_supported("pdf", "jpg") is True
        assert is_route_supported("pdf", "png") is True
        assert is_route_supported("pdf", "jpeg") is True

    def test_output_formats_for_pdf_includes_images(self, tmp_path: Path):
        dummy_pdf = tmp_path / "sample.pdf"
        dummy_pdf.touch()
        formats = output_formats_for(dummy_pdf)
        assert "png" in formats
        assert "jpeg" in formats

    def test_applicable_options_png(self):
        options = get_applicable_options("pdf", "png")
        option_names = {opt.name for opt in options}
        assert "dpi" in option_names
        assert "pages" in option_names
        assert "output_pattern" in option_names
        assert "quality" not in option_names

    def test_applicable_options_jpeg(self):
        options = get_applicable_options("pdf", "jpeg")
        option_names = {opt.name for opt in options}
        assert "dpi" in option_names
        assert "pages" in option_names
        assert "output_pattern" in option_names
        assert "quality" in option_names
        assert "jpeg_background" in option_names


# ===========================================================================
# 2. Page Selection Parsing
# ===========================================================================

class TestPageSelectionParsing:
    def test_default_all_pages(self):
        assert parse_page_selection("all", 5) == (1, 2, 3, 4, 5)
        assert parse_page_selection("", 3) == (1, 2, 3)

    def test_single_page(self):
        assert parse_page_selection(2, 5) == (2,)
        assert parse_page_selection("3", 5) == (3,)

    def test_page_ranges(self):
        assert parse_page_selection("1-3", 5) == (1, 2, 3)
        assert parse_page_selection("2-2", 5) == (2,)

    def test_comma_separated_pages(self):
        assert parse_page_selection("1, 3, 5", 5) == (1, 3, 5)
        assert parse_page_selection("3,1,2", 5) == (3, 1, 2)  # Requested order preserved

    def test_mixed_ranges_and_lists(self):
        assert parse_page_selection("1-2, 4-5", 5) == (1, 2, 4, 5)
        assert parse_page_selection("1, 3-4", 5) == (1, 3, 4)

    def test_sequence_of_ints(self):
        assert parse_page_selection([1, 3, 4], 5) == (1, 3, 4)
        assert parse_page_selection((2,), 5) == (2,)

    def test_out_of_bounds_page_raises(self):
        with pytest.raises(InvalidInputError, match="Page number 6 exceeds total pages 5"):
            parse_page_selection("1, 6", 5)

    def test_zero_or_negative_page_raises(self):
        with pytest.raises(InvalidInputError, match="must be >= 1"):
            parse_page_selection(0, 5)
        with pytest.raises(InvalidInputError, match="must be >= 1"):
            parse_page_selection(-2, 5)

    def test_inverted_range_raises(self):
        with pytest.raises(InvalidInputError, match="Invalid inverted page range"):
            parse_page_selection("4-2", 5)

    def test_invalid_syntax_raises(self):
        with pytest.raises(InvalidInputError, match="Invalid page token"):
            parse_page_selection("abc", 5)
        with pytest.raises(InvalidInputError, match="Invalid page range"):
            parse_page_selection("1-2-3", 5)


# ===========================================================================
# 3. Option Validation & Preflight
# ===========================================================================

class TestOptionValidation:
    def test_valid_options_pass(self):
        opts = {
            "dpi": 200,
            "quality": 85,
            "pages": "1-2",
            "output_pattern": "{stem}_page_{page}.{ext}",
            "jpeg_background": (255, 255, 255),
        }
        validated = validate_options(opts, target_format="jpeg", total_pages=5)
        assert validated["dpi"] == 200
        assert validated["quality"] == 85
        assert validated["pages"] == (1, 2)

    def test_invalid_dpi_raises(self):
        with pytest.raises(InvalidInputError, match="DPI must be an integer between 72 and 400"):
            validate_options({"dpi": 50}, total_pages=5)
        with pytest.raises(InvalidInputError, match="DPI must be an integer between 72 and 400"):
            validate_options({"dpi": 600}, total_pages=5)

    def test_invalid_quality_raises(self):
        with pytest.raises(InvalidInputError, match="JPEG quality must be an integer between 1 and 100"):
            validate_options({"quality": 0}, target_format="jpeg", total_pages=5)
        with pytest.raises(InvalidInputError, match="JPEG quality must be an integer between 1 and 100"):
            validate_options({"quality": 105}, target_format="jpeg", total_pages=5)

    def test_path_traversal_in_pattern_raises(self):
        with pytest.raises(InvalidInputError, match="directory separators"):
            validate_options({"output_pattern": "../{stem}_{page}.png"}, total_pages=5)
        with pytest.raises(InvalidInputError, match="directory separators"):
            validate_options({"output_pattern": "sub/{stem}_{page}.png"}, total_pages=5)

    def test_preflight_catches_invalid_options(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
            options={"dpi": 500},
        )
        findings = validate_preflight(req)
        assert any(f.field == "options.dpi" and f.severity == FindingSeverity.ERROR for f in findings)


# ===========================================================================
# 4. Single-Page PDF Conversions
# ===========================================================================

class TestSinglePageConversion:
    def test_pdf_to_png_single_page(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        assert result.output_path.name == "doc_01_simple_digital.png"
        assert result.output_paths == (result.output_path,)
        assert result.output_bytes > 0

        # Validate PNG header and PIL readability
        raw_bytes = result.output_path.read_bytes()
        assert raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(result.output_path) as im:
            assert im.format == "PNG"
            assert im.width > 100
            assert im.height > 100

    def test_pdf_to_jpeg_single_page(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="jpeg",
            output_dir=tmp_path,
            options={"quality": 80},
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        assert result.output_path.name == "doc_01_simple_digital.jpeg"

        # Validate JPEG header and PIL readability
        raw_bytes = result.output_path.read_bytes()
        assert raw_bytes[:3] == b"\xff\xd8\xff"
        with Image.open(result.output_path) as im:
            assert im.format == "JPEG"
            assert im.mode == "RGB"

    def test_dpi_scaling(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        dir_72 = tmp_path / "dpi72"
        dir_144 = tmp_path / "dpi144"

        res_72 = convert_request(
            ConversionRequest(source=pdf_path, target_format="png", output_dir=dir_72, options={"dpi": 72})
        )
        res_144 = convert_request(
            ConversionRequest(source=pdf_path, target_format="png", output_dir=dir_144, options={"dpi": 144})
        )

        with Image.open(res_72.output_path) as im72, Image.open(res_144.output_path) as im144:
            # 144 DPI should be approximately 2x dimension of 72 DPI
            assert abs(im144.width - (im72.width * 2)) <= 2
            assert abs(im144.height - (im72.height * 2)) <= 2


# ===========================================================================
# 5. Multipage PDF Export & Naming
# ===========================================================================

class TestMultipagePdfExport:
    def test_multipage_pdf_exports_all_pages(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        assert len(result.output_paths) == 3
        assert result.output_path == result.output_paths[0]

        expected_names = [
            "doc_02_multipage_digital_page_1.png",
            "doc_02_multipage_digital_page_2.png",
            "doc_02_multipage_digital_page_3.png",
        ]
        actual_names = [p.name for p in result.output_paths]
        assert actual_names == expected_names

        for p in result.output_paths:
            assert p.is_file()
            assert p.stat().st_size > 0
            with Image.open(p) as im:
                assert im.format == "PNG"

    def test_multipage_subset_selection(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
            options={"pages": "1, 3"},
        )
        result = convert_request(req)

        assert len(result.output_paths) == 2
        actual_names = [p.name for p in result.output_paths]
        assert actual_names == [
            "doc_02_multipage_digital_page_1.png",
            "doc_02_multipage_digital_page_3.png",
        ]

    def test_multipage_single_page_selection(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
            options={"pages": 2},
        )
        result = convert_request(req)

        assert len(result.output_paths) == 1
        assert result.output_paths[0].name == "doc_02_multipage_digital_page_2.png"

    def test_custom_output_pattern(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="jpeg",
            output_dir=tmp_path,
            options={"output_pattern": "{stem}_p{page:02d}.{ext}"},
        )
        result = convert_request(req)

        assert len(result.output_paths) == 3
        actual_names = [p.name for p in result.output_paths]
        assert actual_names == [
            "doc_02_multipage_digital_p01.jpeg",
            "doc_02_multipage_digital_p02.jpeg",
            "doc_02_multipage_digital_p03.jpeg",
        ]

    def test_multipage_missing_page_token_raises(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
            options={"output_pattern": "{stem}.{ext}"},
        )
        with pytest.raises(InvalidInputError, match="must contain '{page}'"):
            convert_request(req)


# ===========================================================================
# 6. Collision Avoidance & Atomicity
# ===========================================================================

class TestCollisionAvoidance:
    def test_existing_files_not_overwritten(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        # Pre-create the target file
        existing = tmp_path / "doc_01_simple_digital.png"
        existing.write_bytes(b"EXISTING_CONTENT")

        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        # Pre-existing file retained
        assert existing.read_bytes() == b"EXISTING_CONTENT"
        # New file gets Windows-style collision suffix
        assert result.output_path.name == "doc_01_simple_digital (2).png"
        assert result.output_path.is_file()

    def test_multipage_collision_avoidance(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        # Pre-create page 1
        p1 = tmp_path / "doc_02_multipage_digital_page_1.png"
        p1.write_bytes(b"ORIGINAL_PAGE_1")

        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        # Original untouched
        assert p1.read_bytes() == b"ORIGINAL_PAGE_1"
        # Page 1 converted with collision resolution
        assert result.output_paths[0].name == "doc_02_multipage_digital_page_1 (2).png"
        # Pages 2 and 3 uncollided
        assert result.output_paths[1].name == "doc_02_multipage_digital_page_2.png"
        assert result.output_paths[2].name == "doc_02_multipage_digital_page_3.png"


# ===========================================================================
# 7. Cancellation & Cleanup
# ===========================================================================

class TestCancellationAndCleanup:
    def test_cancellation_cleans_up_files(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"

        cancelled = False

        def cancel_check() -> bool:
            return cancelled

        # We cancel after page 1 starts
        call_count = 0

        def dynamic_cancel() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count > 1

        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )

        with pytest.raises(ConversionCancelledError):
            convert_request(req, cancel_check=dynamic_cancel)

        # Verify no permanent or partial files left behind
        remaining = list(tmp_path.iterdir())
        assert remaining == []


# ===========================================================================
# 8. Error Handling & Edge Cases
# ===========================================================================

class TestErrorHandling:
    def test_encrypted_pdf_rejected(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_10_encrypted.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        with pytest.raises((InvalidInputError, ConversionFailedError)):
            convert_request(req)

    def test_corrupt_pdf_rejected(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_09_corrupt.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        with pytest.raises((InvalidInputError, ConversionFailedError)):
            convert_request(req)

    def test_zero_page_selection_rejected(self):
        with pytest.raises(InvalidInputError, match="PDF document contains 0 pages"):
            parse_page_selection("all", 0)

    def test_blank_page_pdf_exports_image(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_13_empty.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        result = convert_request(req)
        assert result.output_path.is_file()
        with Image.open(result.output_path) as im:
            assert im.format == "PNG"
            assert im.width > 0

    def test_zero_byte_source_rejected(self, tmp_path: Path):
        empty_file = tmp_path / "empty.pdf"
        empty_file.touch()
        req = ConversionRequest(
            source=empty_file,
            target_format="png",
            output_dir=tmp_path,
        )
        with pytest.raises(InvalidInputError):
            convert_request(req)

    def test_nonexistent_source_rejected(self, tmp_path: Path):
        ghost = tmp_path / "does_not_exist.pdf"
        req = ConversionRequest(
            source=ghost,
            target_format="png",
            output_dir=tmp_path,
        )
        with pytest.raises(InvalidInputError):
            convert_request(req)


# ===========================================================================
# 9. High-Level APIs (convert_image, JobQueue)
# ===========================================================================

class TestHighLevelIntegration:
    def test_convert_image_wrapper_png(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        out_path = convert_image(pdf_path, "png", output_dir=tmp_path)
        assert out_path.is_file()
        assert out_path.suffix.lower() == ".png"

    def test_convert_image_wrapper_jpeg(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        out_path = convert_image(pdf_path, "jpeg", output_dir=tmp_path)
        assert out_path.is_file()
        assert out_path.suffix.lower() == ".jpeg"

    def test_job_queue_submission(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        queue = JobQueue(max_workers=1)
        job = queue.submit(
            source=pdf_path,
            target_format="png",
            output_dir=tmp_path,
        )
        queue.shutdown(wait=True)
        res = queue.get_result(job.job_id)
        assert res.status == JobStatus.SUCCEEDED
        assert res.output_path.is_file()
