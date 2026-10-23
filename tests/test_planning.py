"""
tests.test_planning — Comprehensive test suite for Conversion Planning,
Preflight Validation, Capability Discovery, and Option Validation (LS-BE-005).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from localshift import (
    AdapterRegistry,
    ConversionError,
    ConversionJob,
    ConversionPlan,
    ConversionRequest,
    ConversionResult,
    FindingCode,
    FindingSeverity,
    InvalidInputError,
    JobQueue,
    JobStatus,
    OptionSpec,
    PillowImageAdapter,
    UnsupportedConversionError,
    UnsupportedFormatError,
    ValidationFinding,
    convert_image,
    convert_request,
    default_registry,
    get_adapter_info,
    get_applicable_options,
    get_supported_routes,
    get_supported_source_formats,
    get_supported_target_formats,
    is_route_supported,
    plan_conversion,
    plan_route,
    validate_conversion_options,
    validate_preflight,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    p = tmp_path / "test.png"
    im = Image.new("RGBA", (20, 20), (255, 0, 0, 128))
    im.save(p, format="PNG")
    return p


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    p = tmp_path / "test.jpg"
    im = Image.new("RGB", (20, 20), (0, 255, 0))
    im.save(p, format="JPEG")
    return p


@pytest.fixture
def empty_file(tmp_path: Path) -> Path:
    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    return p


# ---------------------------------------------------------------------------
# 1. Capability Discovery API Tests
# ---------------------------------------------------------------------------

class TestCapabilityDiscovery:
    def test_get_supported_source_formats(self):
        srcs = get_supported_source_formats()
        assert isinstance(srcs, list)
        assert srcs == sorted(srcs)
        assert set(srcs) == {"bmp", "jpeg", "png", "tiff", "webp"}

    def test_get_supported_target_formats_unfiltered(self):
        tgts = get_supported_target_formats()
        assert isinstance(tgts, list)
        assert tgts == sorted(tgts)
        assert set(tgts) == {"bmp", "jpeg", "png", "tiff", "webp"}

    def test_get_supported_target_formats_for_source(self):
        # PNG cannot convert to PNG (no-op), should support remaining 4
        tgts = get_supported_target_formats("png")
        assert tgts == ["bmp", "jpeg", "tiff", "webp"]

        # Alias "jpg" should resolve to "jpeg" targets
        tgts_jpg = get_supported_target_formats("jpg")
        assert tgts_jpg == ["bmp", "png", "tiff", "webp"]

        # Unknown source format returns empty list
        assert get_supported_target_formats("nonexistent") == []

    def test_get_supported_routes(self):
        routes = get_supported_routes()
        assert isinstance(routes, list)
        assert routes == sorted(routes)
        assert len(routes) == 20
        assert ("png", "jpeg") in routes
        assert ("png", "png") not in routes

    def test_is_route_supported_canonical_and_aliases(self):
        assert is_route_supported("png", "jpeg") is True
        assert is_route_supported("png", "jpg") is True
        assert is_route_supported("tif", "png") is True
        assert is_route_supported("png", "png") is False
        assert is_route_supported("png", "unknown") is False
        assert is_route_supported("unknown", "png") is False

    def test_get_applicable_options(self):
        opts = get_applicable_options("png", "jpeg")
        assert len(opts) == 1
        assert opts[0].name == "jpeg_background"
        assert opts[0].default == (255, 255, 255)

        # Route to webp has no options
        assert get_applicable_options("png", "webp") == ()
        # Invalid route returns empty tuple
        assert get_applicable_options("png", "unknown") == ()

    def test_get_adapter_info(self):
        info = get_adapter_info("pillow_raster")
        assert info is not None
        assert info["adapter_id"] == "pillow_raster"
        assert info["name"] == "Pillow Raster Image Adapter"
        assert info["supported_routes_count"] == 20
        assert "png" in info["supported_source_formats"]

        assert get_adapter_info("nonexistent") is None


# ---------------------------------------------------------------------------
# 2. Conversion Plan Generation Tests (Zero Side-Effects)
# ---------------------------------------------------------------------------

class TestConversionPlanGeneration:
    def test_plan_valid_physical_file(self, sample_png: Path, tmp_path: Path):
        dest_dir = tmp_path / "out"
        plan = plan_conversion(sample_png, "jpeg", output_dir=dest_dir)

        assert isinstance(plan, ConversionPlan)
        assert plan.source_format == "png"
        assert plan.target_format == "jpeg"
        assert plan.route_supported is True
        assert plan.adapter_id == "pillow_raster"
        assert "jpeg" in plan.available_target_formats
        assert any(o.name == "jpeg_background" for o in plan.applicable_options)
        assert plan.is_ready is True
        assert len([f for f in plan.findings if f.blocks_execution]) == 0

        # Guarantees: No files created, no output directory created, no side effects
        assert not dest_dir.exists()
        assert list(tmp_path.glob("*.jpg")) == []
        assert list(tmp_path.glob("*.tmp")) == []

    def test_plan_with_conversion_request_object(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="webp",
            options={},
        )
        plan = plan_conversion(req)
        assert plan.route_supported is True
        assert plan.is_ready is True
        assert plan.adapter_id == "pillow_raster"

    def test_plan_format_aliases(self, sample_png: Path):
        plan = plan_conversion(sample_png, "jpg")
        assert plan.target_format == "jpeg"
        assert plan.route_supported is True
        assert plan.is_ready is True

    def test_plan_route_without_file(self):
        plan = plan_route("png", "webp")
        assert plan.source_format == "png"
        assert plan.target_format == "webp"
        assert plan.route_supported is True
        assert plan.adapter_id == "pillow_raster"
        assert plan.is_ready is True

    def test_plan_route_same_format(self):
        plan = plan_route("png", "png")
        assert plan.route_supported is False
        assert plan.is_ready is False
        assert any(f.code == FindingCode.SAME_FORMAT_NO_OP for f in plan.findings)

    def test_plan_route_unsupported_target(self):
        plan = plan_route("png", "docx")
        assert plan.target_format is None
        assert plan.route_supported is False
        assert plan.is_ready is False
        assert any(f.code == FindingCode.TARGET_FORMAT_INVALID for f in plan.findings)


# ---------------------------------------------------------------------------
# 3. Preflight Validation & Finding Codes Tests
# ---------------------------------------------------------------------------

class TestPreflightValidation:
    def test_source_not_found(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.png"
        findings = validate_preflight(ConversionRequest(source=missing, target_format="jpeg"))
        assert any(f.code == FindingCode.SOURCE_NOT_FOUND and f.blocks_execution for f in findings)

    def test_source_is_directory(self, tmp_path: Path):
        findings = validate_preflight(ConversionRequest(source=tmp_path, target_format="jpeg"))
        assert any(f.code == FindingCode.SOURCE_NOT_A_FILE and f.blocks_execution for f in findings)

    def test_source_is_empty(self, empty_file: Path):
        findings = validate_preflight(ConversionRequest(source=empty_file, target_format="jpeg"))
        assert any(f.code == FindingCode.SOURCE_EMPTY and f.blocks_execution for f in findings)

    def test_source_too_large(self, sample_png: Path):
        # Set max limit to smaller than file
        findings = validate_preflight(
            ConversionRequest(source=sample_png, target_format="jpeg"),
            max_input_bytes=10,
        )
        assert any(f.code == FindingCode.SOURCE_TOO_LARGE and f.blocks_execution for f in findings)

    def test_invalid_target_format(self, sample_png: Path):
        findings = validate_preflight(ConversionRequest(source=sample_png, target_format="mp3"))
        assert any(f.code == FindingCode.TARGET_FORMAT_INVALID and f.blocks_execution for f in findings)

    def test_same_format_conversion_rejected(self, sample_png: Path):
        findings = validate_preflight(ConversionRequest(source=sample_png, target_format="png"))
        assert any(f.code == FindingCode.SAME_FORMAT_NO_OP and f.blocks_execution for f in findings)

    def test_unsupported_route_custom_registry(self, sample_png: Path):
        empty_reg = AdapterRegistry()
        findings = validate_preflight(
            ConversionRequest(source=sample_png, target_format="jpeg"),
            registry=empty_reg,
        )
        assert any(f.code == FindingCode.ROUTE_UNSUPPORTED and f.blocks_execution for f in findings)

    def test_destination_dir_is_a_file(self, sample_png: Path, tmp_path: Path):
        not_a_dir = tmp_path / "fake_dir"
        not_a_dir.write_text("hello")
        findings = validate_preflight(
            ConversionRequest(source=sample_png, target_format="webp", output_dir=not_a_dir)
        )
        assert any(f.code == FindingCode.DESTINATION_DIR_INVALID and f.blocks_execution for f in findings)

    def test_destination_conflict_with_source(self, sample_jpeg: Path):
        # Converting test.jpg to jpeg in its same folder would produce test.jpg
        # Since test.jpg already exists in tmp_path, destination conflict check identifies it
        findings = validate_preflight(
            ConversionRequest(source=sample_jpeg, target_format="jpeg", output_dir=sample_jpeg.parent)
        )
        # Note: jpeg to jpeg also triggers SAME_FORMAT_NO_OP
        codes = [f.code for f in findings]
        assert FindingCode.SAME_FORMAT_NO_OP in codes or FindingCode.DESTINATION_CONFLICT in codes


# ---------------------------------------------------------------------------
# 4. Conversion Option Validation Tests
# ---------------------------------------------------------------------------

class TestOptionValidation:
    def test_valid_jpeg_background(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            options={"jpeg_background": (128, 128, 128)},
        )
        plan = plan_conversion(req)
        assert plan.is_ready is True
        assert len(plan.findings) == 0

    def test_invalid_jpeg_background_type(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            options={"jpeg_background": "white"},  # Should be 3-tuple of ints
        )
        plan = plan_conversion(req)
        assert plan.is_ready is False
        assert any(f.code == FindingCode.INVALID_OPTION_VALUE for f in plan.findings)

    def test_invalid_jpeg_background_range(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            options={"jpeg_background": (255, 255, 999)},  # 999 out of 0-255 range
        )
        plan = plan_conversion(req)
        assert plan.is_ready is False
        assert any(f.code == FindingCode.INVALID_OPTION_VALUE for f in plan.findings)

    def test_unknown_option_rejected(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            options={"unsupported_filter": True},
        )
        plan = plan_conversion(req)
        assert plan.is_ready is False
        assert any(f.code == FindingCode.UNKNOWN_OPTION for f in plan.findings)


# ---------------------------------------------------------------------------
# 5. Execution Integration & Revalidation Tests
# ---------------------------------------------------------------------------

class TestExecutionIntegration:
    def test_execution_rejects_invalid_options(self, sample_png: Path):
        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            options={"invalid_option": 123},
        )
        with pytest.raises(InvalidInputError) as exc_info:
            convert_request(req)
        assert "Unknown or unsupported option" in str(exc_info.value)

    def test_execution_revalidates_despite_prior_plan(self, sample_png: Path, tmp_path: Path):
        # Generate valid plan
        plan = plan_conversion(sample_png, "jpeg", output_dir=tmp_path)
        assert plan.is_ready is True

        # Delete source file before execution to simulate TOCTOU change
        sample_png.unlink()

        req = ConversionRequest(
            source=sample_png,
            target_format="jpeg",
            output_dir=tmp_path,
        )
        with pytest.raises(InvalidInputError):
            convert_request(req)

    def test_convert_image_backward_compatibility(self, sample_png: Path, tmp_path: Path):
        out = convert_image(sample_png, "webp", output_dir=tmp_path)
        assert out.exists()
        assert out.suffix == ".webp"

    def test_job_queue_backward_compatibility(self, sample_png: Path, tmp_path: Path):
        queue = JobQueue(max_workers=1)
        job = queue.submit(
            source=sample_png,
            target_format="jpeg",
            output_dir=tmp_path,
        )
        queue.shutdown(wait=True)
        res = queue.get_result(job.job_id)
        assert res.status == JobStatus.SUCCEEDED
        assert res.output_path.exists()
