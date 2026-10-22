"""
tests/test_adapters.py — Unit and integration tests for the adapter architecture,
capability registry, and error taxonomy (LS-BE-004).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from localshift import (
    AdapterRegistrationError,
    AdapterRegistry,
    AdapterUnavailableError,
    ConversionAdapter,
    ConversionCancelledError,
    ConversionContext,
    ConversionError,
    ConversionFailedError,
    ConversionJob,
    ConversionRequest,
    ConversionResult,
    DestinationConflictError,
    InputTooLargeError,
    InvalidInputError,
    JobQueue,
    JobStatus,
    PillowImageAdapter,
    UnsupportedConversionError,
    UnsupportedFormatError,
    convert_image,
    convert_request,
    default_registry,
)
from localshift.formats import output_formats_for, route_supported


# ---------------------------------------------------------------------------
# Test Helpers & Dummy Adapters
# ---------------------------------------------------------------------------

def _make_image(path: Path, mode: str = "RGBA", size: tuple[int, int] = (10, 10)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, (255, 0, 0, 128) if "A" in mode else (255, 0, 0)).save(path, format="PNG")
    return path


class DummyAdapter:
    """A minimal mock adapter for registry and routing tests."""

    def __init__(
        self,
        adapter_id: str = "dummy_adapter",
        routes: frozenset[tuple[str, str]] = frozenset([("text", "pdf")]),
    ) -> None:
        self.adapter_id = adapter_id
        self.name = f"Dummy Adapter ({adapter_id})"
        self._routes = routes
        self._srcs = frozenset(s for s, _ in routes)
        self._tgts = frozenset(t for _, t in routes)

    @property
    def supported_source_formats(self) -> frozenset[str]:
        return self._srcs

    @property
    def supported_target_formats(self) -> frozenset[str]:
        return self._tgts

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        return self._routes

    def can_convert(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self._routes

    def convert(self, request: ConversionRequest, context: ConversionContext) -> ConversionResult:
        context.check_cancelled()
        # Mock writing to temp_output_path
        context.temp_output_path.write_bytes(b"dummy output content")
        return ConversionResult(
            output_path=context.temp_output_path,
            source_format=request.source_format or "text",
            target_format=context.target_format,
            input_bytes=10,
            output_bytes=20,
            adapter_id=self.adapter_id,
        )


# ---------------------------------------------------------------------------
# Test Suite: Adapter Protocol & Contract Conformance
# ---------------------------------------------------------------------------

class TestAdapterContract:
    def test_pillow_adapter_conforms_to_protocol(self):
        adapter = PillowImageAdapter()
        assert isinstance(adapter, ConversionAdapter)
        assert adapter.adapter_id == "pillow_raster"
        assert adapter.name == "Pillow Raster Image Adapter"
        assert isinstance(adapter.supported_routes, frozenset)
        assert len(adapter.supported_routes) == 20  # 5 formats * 4 targets

    def test_dummy_adapter_conforms_to_protocol(self):
        adapter = DummyAdapter()
        assert isinstance(adapter, ConversionAdapter)

    def test_protocol_rejects_missing_methods(self):
        class IncompleteAdapter:
            adapter_id = "incomplete"

        assert not isinstance(IncompleteAdapter(), ConversionAdapter)


# ---------------------------------------------------------------------------
# Test Suite: Registry Lifecycle & Route Management
# ---------------------------------------------------------------------------

class TestAdapterRegistry:
    def test_register_and_lookup_adapter(self):
        reg = AdapterRegistry()
        adapter = DummyAdapter("test1", frozenset([("foo", "bar")]))
        reg.register(adapter)

        assert reg.can_convert("foo", "bar")
        assert not reg.can_convert("bar", "foo")
        assert reg.get_adapter("foo", "bar") is adapter
        assert reg.get_adapter_by_id("test1") is adapter
        assert adapter in reg.list_adapters()

    def test_duplicate_adapter_id_rejected_by_default(self):
        reg = AdapterRegistry()
        a1 = DummyAdapter("dup_id", frozenset([("foo", "bar")]))
        a2 = DummyAdapter("dup_id", frozenset([("baz", "qux")]))
        reg.register(a1)

        with pytest.raises(AdapterRegistrationError, match="already registered"):
            reg.register(a2)

    def test_duplicate_adapter_id_allowed_with_override(self):
        reg = AdapterRegistry()
        a1 = DummyAdapter("dup_id", frozenset([("foo", "bar")]))
        a2 = DummyAdapter("dup_id", frozenset([("baz", "qux")]))
        reg.register(a1)
        reg.register(a2, allow_override=True)

        assert reg.get_adapter_by_id("dup_id") is a2
        assert reg.can_convert("baz", "qux")

    def test_conflicting_route_rejected_by_default(self):
        reg = AdapterRegistry()
        a1 = DummyAdapter("adapter_1", frozenset([("shared", "target")]))
        a2 = DummyAdapter("adapter_2", frozenset([("shared", "target")]))
        reg.register(a1)

        with pytest.raises(AdapterRegistrationError, match="Route conflict"):
            reg.register(a2)

    def test_conflicting_route_allowed_with_override(self):
        reg = AdapterRegistry()
        a1 = DummyAdapter("adapter_1", frozenset([("shared", "target")]))
        a2 = DummyAdapter("adapter_2", frozenset([("shared", "target")]))
        reg.register(a1)
        reg.register(a2, allow_override=True)

        assert reg.get_adapter("shared", "target") is a2

    def test_invalid_adapter_id_rejected(self):
        reg = AdapterRegistry()
        bad = DummyAdapter("", frozenset([("a", "b")]))
        with pytest.raises(AdapterRegistrationError, match="non-empty string"):
            reg.register(bad)

    def test_unregister_removes_routes_and_adapter(self):
        reg = AdapterRegistry()
        adapter = DummyAdapter("to_remove", frozenset([("a", "b"), ("c", "d")]))
        reg.register(adapter)
        assert reg.can_convert("a", "b")

        removed = reg.unregister("to_remove")
        assert removed is adapter
        assert not reg.can_convert("a", "b")
        assert reg.get_adapter_by_id("to_remove") is None

    def test_unregister_nonexistent_returns_none(self):
        reg = AdapterRegistry()
        assert reg.unregister("non_existent") is None

    def test_snapshot_provides_isolated_copy(self):
        reg = AdapterRegistry()
        adapter = DummyAdapter("snap", frozenset([("x", "y")]))
        reg.register(adapter)

        snap = reg.snapshot()
        assert snap.can_convert("x", "y")

        # Mutating original does not mutate snapshot
        adapter2 = DummyAdapter("snap2", frozenset([("m", "n")]))
        reg.register(adapter2)
        assert reg.can_convert("m", "n")
        assert not snap.can_convert("m", "n")

    def test_default_registry_has_pillow_pre_registered(self):
        assert default_registry.can_convert("png", "jpeg")
        assert default_registry.get_adapter_by_id("pillow_raster") is not None


# ---------------------------------------------------------------------------
# Test Suite: Capability Discovery & Format Queries
# ---------------------------------------------------------------------------

class TestCapabilityDiscovery:
    def test_supported_sources_and_targets(self):
        reg = AdapterRegistry()
        adapter = DummyAdapter("test", frozenset([("png", "jpeg"), ("png", "webp"), ("bmp", "jpeg")]))
        reg.register(adapter)

        assert reg.supported_source_formats() == frozenset({"png", "bmp"})
        assert reg.supported_target_formats() == frozenset({"jpeg", "webp"})
        assert reg.supported_target_formats("png") == frozenset({"jpeg", "webp"})
        assert reg.supported_target_formats("bmp") == frozenset({"jpeg"})
        assert reg.supported_target_formats("unknown") == frozenset()

    def test_formats_py_output_formats_for_uses_registry(self, tmp_path):
        src = tmp_path / "test.png"
        src.touch()
        targets = output_formats_for(src)
        assert sorted(targets) == ["bmp", "jpeg", "tiff", "webp"]

    def test_formats_py_output_formats_for_unknown_returns_empty(self, tmp_path):
        src = tmp_path / "test.xyz"
        src.touch()
        assert output_formats_for(src) == []

    def test_formats_py_route_supported_uses_registry(self):
        assert route_supported("png", "jpeg")
        assert route_supported("PNG", "JPG")  # Case & alias normalization
        assert not route_supported("png", "png")  # Identity route rejected
        assert not route_supported("png", "unknown_format")


# ---------------------------------------------------------------------------
# Test Suite: Error Taxonomy & Hierarchy
# ---------------------------------------------------------------------------

class TestErrorTaxonomy:
    def test_hierarchy_relationships(self):
        # All conversion exceptions inherit from ConversionError
        assert issubclass(UnsupportedFormatError, ConversionError)
        assert issubclass(UnsupportedConversionError, ConversionError)
        assert issubclass(InvalidInputError, ConversionError)
        assert issubclass(InputTooLargeError, InvalidInputError)
        assert issubclass(DestinationConflictError, ConversionError)
        assert issubclass(AdapterUnavailableError, ConversionError)
        assert issubclass(ConversionFailedError, ConversionError)
        assert issubclass(ConversionCancelledError, ConversionError)

    def test_unsupported_format_error_is_also_value_error(self):
        # Ensures existing code expecting ValueError also catches UnsupportedFormatError
        assert issubclass(UnsupportedFormatError, ValueError)

    def test_unsupported_conversion_raises_specific_error(self, tmp_path):
        src = _make_image(tmp_path / "test.png")
        reg = AdapterRegistry()  # Empty registry

        req = ConversionRequest(source=src, target_format="jpeg")
        with pytest.raises(UnsupportedConversionError) as exc_info:
            convert_request(req, registry=reg)
        assert isinstance(exc_info.value, ConversionError)

    def test_invalid_input_file_raises_invalid_input_error(self, tmp_path):
        req = ConversionRequest(source=tmp_path / "missing.png", target_format="jpeg")
        with pytest.raises(InvalidInputError) as exc_info:
            convert_request(req)
        assert isinstance(exc_info.value, ConversionError)

    def test_input_too_large_raises_specific_error(self, tmp_path):
        src = _make_image(tmp_path / "large.png")
        req = ConversionRequest(source=src, target_format="jpeg")
        with pytest.raises(InputTooLargeError) as exc_info:
            convert_request(req, max_input_bytes=10)
        assert isinstance(exc_info.value, InvalidInputError)
        assert isinstance(exc_info.value, ConversionError)

    def test_destination_conflict_raises_specific_error(self, tmp_path):
        src = _make_image(tmp_path / "photo.png")
        # Attempt to produce output at identical path
        req = ConversionRequest(source=src, target_format="png", output_dir=tmp_path)
        with pytest.raises(UnsupportedConversionError):
            convert_request(req)


# ---------------------------------------------------------------------------
# Test Suite: Core Engine Security Boundary & Result Verification
# ---------------------------------------------------------------------------

class TestSecurityBoundaryAndResultVerification:
    def test_adapter_cannot_bypass_output_verification(self, tmp_path):
        """If an adapter completes without creating context.temp_output_path,
        the core engine detects it and raises ConversionFailedError."""
        src = _make_image(tmp_path / "input.png")

        class BrokenAdapter:
            adapter_id = "broken_adapter"
            name = "Broken Adapter"
            supported_source_formats = frozenset({"png"})
            supported_target_formats = frozenset({"jpeg"})
            supported_routes = frozenset([("png", "jpeg")])

            def can_convert(self, s, t):
                return (s, t) == ("png", "jpeg")

            def convert(self, req, ctx):
                # Intentional bug: does NOT write context.temp_output_path
                return ConversionResult(
                    output_path=ctx.temp_output_path,
                    source_format="png",
                    target_format="jpeg",
                    input_bytes=10,
                    output_bytes=0,
                )

        reg = AdapterRegistry()
        reg.register(BrokenAdapter())

        req = ConversionRequest(source=src, target_format="jpeg", output_dir=tmp_path)
        with pytest.raises(ConversionFailedError, match="valid output file"):
            convert_request(req, registry=reg)

        # Ensure no temp files leak
        assert list(tmp_path.glob("*.tmp")) == []

    def test_adapter_failure_cleans_up_temp_and_reservation(self, tmp_path):
        src = _make_image(tmp_path / "input.png")

        class FailingAdapter:
            adapter_id = "failing_adapter"
            name = "Failing Adapter"
            supported_source_formats = frozenset({"png"})
            supported_target_formats = frozenset({"jpeg"})
            supported_routes = frozenset([("png", "jpeg")])

            def can_convert(self, s, t):
                return (s, t) == ("png", "jpeg")

            def convert(self, req, ctx):
                ctx.temp_output_path.write_bytes(b"partial")
                raise RuntimeError("Hardware failure during encoding")

        reg = AdapterRegistry()
        reg.register(FailingAdapter())

        req = ConversionRequest(source=src, target_format="jpeg", output_dir=tmp_path)
        with pytest.raises(ConversionFailedError, match="Hardware failure"):
            convert_request(req, registry=reg)

        # Temporary file should have been cleaned up
        assert list(tmp_path.glob("*.tmp")) == []

    def test_cancellation_before_execution(self, tmp_path):
        src = _make_image(tmp_path / "input.png")
        req = ConversionRequest(source=src, target_format="jpeg", output_dir=tmp_path)

        with pytest.raises(ConversionCancelledError, match="cancelled before"):
            convert_request(req, cancel_check=lambda: True)


# ---------------------------------------------------------------------------
# Test Suite: PillowImageAdapter Full Execution
# ---------------------------------------------------------------------------

class TestPillowImageAdapterExecution:
    def test_convert_request_basic(self, tmp_path):
        src = _make_image(tmp_path / "sample.png", mode="RGB")
        out_dir = tmp_path / "out"

        req = ConversionRequest(source=src, target_format="jpeg", output_dir=out_dir)
        res = convert_request(req)

        assert isinstance(res, ConversionResult)
        assert res.output_path.exists()
        assert res.output_path.suffix == ".jpeg"
        assert res.source_format == "png"
        assert res.target_format == "jpeg"
        assert res.adapter_id == "pillow_raster"
        assert res.output_bytes > 0

    def test_convert_request_with_jpeg_background(self, tmp_path):
        # Semi-transparent RGBA PNG converted to JPEG with red background fill
        src = _make_image(tmp_path / "transparent.png", mode="RGBA")
        req = ConversionRequest(
            source=src,
            target_format="jpeg",
            output_dir=tmp_path,
            options={"jpeg_background": (255, 0, 0)},
        )
        res = convert_request(req)
        assert res.output_path.exists()

    def test_convert_image_wrapper_backward_compatibility(self, tmp_path):
        src = _make_image(tmp_path / "input.png")
        out_path = convert_image(src, "webp", tmp_path)

        assert isinstance(out_path, Path)
        assert out_path.exists()
        assert out_path.suffix == ".webp"


# ---------------------------------------------------------------------------
# Test Suite: JobQueue & Integration Compatibility
# ---------------------------------------------------------------------------

def _wait_terminal(q: JobQueue, job_id: str, timeout: float = 5.0) -> JobStatus:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = q.get_status(job_id)
        if res in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            return res
        time.sleep(0.01)
    pytest.fail(f"Job {job_id[:8]} did not reach terminal status within {timeout}s")


class TestJobQueueAdapterIntegration:
    def test_job_queue_executes_via_adapter(self, tmp_path):
        src = _make_image(tmp_path / "job_in.png")
        with JobQueue(max_workers=1) as q:
            job = q.submit(src, "jpeg", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
            res = q.get_result(job.job_id)

        assert res.status is JobStatus.SUCCEEDED
        assert res.output_path is not None
        assert res.output_path.exists()

    def test_job_queue_captures_unsupported_route_error(self, tmp_path):
        src = _make_image(tmp_path / "job_in.png")
        with JobQueue(max_workers=1) as q:
            # Submitting same format png -> png is rejected by route check
            job = q.submit(src, "png", output_dir=tmp_path)
            _wait_terminal(q, job.job_id)
            res = q.get_result(job.job_id)

        assert res.status is JobStatus.FAILED
        assert "Unsupported conversion" in res.error
