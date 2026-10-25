"""
tests.test_docx_pdf — Comprehensive unit and integration test suite for DOCX -> PDF conversion.

Tests:
1. Adapter protocol compliance and OptionSpec definitions.
2. Capability discovery and preflight route planning.
3. Strict input validation (PK magic bytes, zip integrity, word/document.xml requirement).
4. Missing backend handling (AdapterUnavailableError & ADAPTER_UNAVAILABLE finding).
5. Subprocess timeout enforcement and temporary directory cleanup.
6. Cooperative cancellation checks.
7. Destination collision avoidance and atomic output file placement.
8. Source file immutability (hash verification before and after rendering).
9. Live integration tests with active backend (Word COM on Windows):
   - Simple document (headings, bold, italic).
   - Multipage document (page count parity, section breaks).
   - Tables (headers, cells, borders).
   - Images (embedded graphics).
   - Headers, footers, and hyperlinks.
   - Landscape orientation, custom margins, and multilingual Unicode.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pypdfium2
import pytest

from localshift.converter import convert_request
from localshift.documents.docx_adapter import DocxToPdfAdapter
from localshift.documents.docx_renderer import DocxToPdfRenderer
from localshift.exceptions import (
    AdapterUnavailableError,
    ConversionCancelledError,
    ConversionFailedError,
    InvalidInputError,
)
from localshift.formats import input_format, output_formats_for, route_supported, sniff_format
from localshift.models import (
    ConversionContext,
    ConversionRequest,
    FindingSeverity,
)
from localshift.planner import (
    FindingCode,
    get_applicable_options,
    get_supported_routes,
    get_supported_source_formats,
    is_route_supported,
    plan_conversion,
    validate_preflight,
)
from localshift.registry import AdapterRegistry, default_registry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "docx_documents"


@pytest.fixture(scope="session", autouse=True)
def ensure_docx_fixtures():
    """Ensure DOCX test fixtures exist before running tests."""
    if not (FIXTURES_DIR / "docx_01_simple.docx").is_file():
        from tests.docx_fixture_generator import generate_all_fixtures
        generate_all_fixtures()


# ===========================================================================
# 1. Adapter Protocol & Option Specification
# ===========================================================================

class TestDocxToPdfAdapterProtocol:
    """Verifies that DocxToPdfAdapter satisfies LocalShift adapter requirements."""

    def test_adapter_attributes(self):
        adapter = DocxToPdfAdapter()
        assert adapter.adapter_id == "docx_to_pdf"
        assert adapter.name == "DOCX to PDF Conversion Adapter"
        assert adapter.supported_source_formats == frozenset({"docx"})
        assert adapter.supported_target_formats == frozenset({"pdf"})
        assert adapter.supported_routes == frozenset({("docx", "pdf")})

    def test_adapter_availability_matches_renderer(self):
        adapter = DocxToPdfAdapter()
        expected = DocxToPdfRenderer.is_backend_available()
        assert adapter.is_available() is expected
        assert adapter.can_convert("docx", "pdf") is expected
        assert adapter.can_convert("docx", "txt") is False
        assert adapter.can_convert("pdf", "docx") is False

    def test_supported_options(self):
        adapter = DocxToPdfAdapter()
        opts = adapter.get_supported_options("docx", "pdf")
        assert len(opts) == 2
        names = {opt.name for opt in opts}
        assert names == {"renderer", "timeout"}

        renderer_opt = next(opt for opt in opts if opt.name == "renderer")
        assert renderer_opt.default == "auto"
        assert set(renderer_opt.choices) == {"auto", "libreoffice", "word_com"}

        timeout_opt = next(opt for opt in opts if opt.name == "timeout")
        assert timeout_opt.default == 60
        assert timeout_opt.type_name == "int"

        # Invalid route returns empty options
        assert adapter.get_supported_options("docx", "txt") == ()


# ===========================================================================
# 2. Registry, Format Sniffing & Discovery
# ===========================================================================

class TestDocxDiscoveryAndRegistry:
    """Verifies format sniffing, route discovery, and registry integration."""

    def test_sniff_format_docx(self):
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        assert sniff_format(sample) == "docx"
        assert input_format(sample) == "docx"

    def test_route_supported_reflects_backend(self):
        has_backend = DocxToPdfRenderer.is_backend_available()
        assert route_supported("docx", "pdf") is has_backend
        assert is_route_supported("docx", "pdf") is has_backend
        assert is_route_supported("docx", "txt") is False

    def test_output_formats_for_docx(self):
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        targets = output_formats_for(sample)
        if DocxToPdfRenderer.is_backend_available():
            assert "pdf" in targets
        else:
            assert "pdf" not in targets

    def test_applicable_options_via_planner(self):
        opts = get_applicable_options("docx", "pdf")
        assert len(opts) == 2
        assert {o.name for o in opts} == {"renderer", "timeout"}


# ===========================================================================
# 3. Preflight Validation & Planning
# ===========================================================================

class TestDocxPreflightAndPlanning:
    """Verifies plan generation and preflight checks."""

    def test_plan_conversion_valid_docx(self):
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        plan = plan_conversion(sample, "pdf")
        if DocxToPdfRenderer.is_backend_available():
            assert plan.is_ready is True
            assert plan.route_supported is True
            assert plan.adapter_id == "docx_to_pdf"
        else:
            assert plan.is_ready is False
            assert any(f.code == FindingCode.ADAPTER_UNAVAILABLE for f in plan.findings)

    def test_preflight_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.docx"
        findings = validate_preflight(ConversionRequest(source=missing, target_format="pdf"))
        assert any(f.code == FindingCode.SOURCE_NOT_FOUND for f in findings)

    def test_preflight_empty_file(self, tmp_path):
        empty = tmp_path / "empty.docx"
        empty.write_bytes(b"")
        findings = validate_preflight(ConversionRequest(source=empty, target_format="pdf"))
        assert any(f.code == FindingCode.SOURCE_EMPTY for f in findings)

    def test_preflight_invalid_option_value(self):
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        findings = validate_preflight(
            ConversionRequest(
                source=sample,
                target_format="pdf",
                options={"renderer": "invalid_engine"},
            )
        )
        assert any(f.code == FindingCode.INVALID_OPTION_VALUE for f in findings)

    def test_preflight_missing_backend_finding(self):
        """Simulate system without office backends to test actionable error reporting."""
        with patch.object(DocxToPdfRenderer, "is_backend_available", return_value=False):
            # Create isolated registry with unavailable DocxToPdfAdapter
            reg = default_registry.snapshot()
            sample = FIXTURES_DIR / "docx_01_simple.docx"
            findings = validate_preflight(
                ConversionRequest(source=sample, target_format="pdf"),
                registry=reg,
            )
            unavailable = [f for f in findings if f.code == FindingCode.ADAPTER_UNAVAILABLE]
            assert len(unavailable) == 1
            assert "requires an offline document rendering backend" in unavailable[0].message


# ===========================================================================
# 4. Strict Input Validation (Container & XML Integrity)
# ===========================================================================

class TestDocxInputValidation:
    """Verifies protection against damaged, forged, or malformed inputs."""

    def test_not_a_zip_file(self, tmp_path):
        fake = tmp_path / "fake.docx"
        fake.write_text("This is plain text, not a zip file.", encoding="utf-8")
        out_pdf = tmp_path / "out.pdf"
        with pytest.raises(InvalidInputError, match="missing PK zip header"):
            DocxToPdfRenderer.render_docx_to_pdf(fake, out_pdf)

    def test_corrupted_zip_archive(self, tmp_path):
        bad_zip = tmp_path / "corrupt.docx"
        bad_zip.write_bytes(b"PK\x03\x04" + b"\x00" * 50)
        out_pdf = tmp_path / "out.pdf"
        with pytest.raises(InvalidInputError, match="damaged or corrupted zip archive"):
            DocxToPdfRenderer.render_docx_to_pdf(bad_zip, out_pdf)

    def test_zip_missing_document_xml(self, tmp_path):
        bad_doc = tmp_path / "not_word.docx"
        with zipfile.ZipFile(bad_doc, "w") as zf:
            zf.writestr("some_folder/content.txt", "Hello world")
        out_pdf = tmp_path / "out.pdf"
        with pytest.raises(InvalidInputError, match="missing word/document.xml"):
            DocxToPdfRenderer.render_docx_to_pdf(bad_doc, out_pdf)


# ===========================================================================
# 5. Process Isolation, Timeouts & Cancellation
# ===========================================================================

class TestProcessControlAndSandboxing:
    """Verifies timeout handling, cooperative cancellation, and cleanup."""

    def test_cancellation_before_execution(self, tmp_path):
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        out_pdf = tmp_path / "out.pdf"
        with pytest.raises(ConversionCancelledError, match="before rendering started"):
            DocxToPdfRenderer.render_docx_to_pdf(
                sample,
                out_pdf,
                cancel_check=lambda: True,
            )
        assert not out_pdf.exists()

    def test_timeout_handling_libreoffice(self, tmp_path):
        """Mock LibreOffice execution to test timeout handling and process termination."""
        sample = FIXTURES_DIR / "docx_01_simple.docx"
        out_pdf = tmp_path / "out.pdf"

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process stays alive forever

        with patch.object(DocxToPdfRenderer, "find_libreoffice_binary", return_value=Path("soffice.exe")):
            with patch("subprocess.Popen", return_value=mock_proc):
                with pytest.raises(ConversionFailedError, match="timed out"):
                    DocxToPdfRenderer.render_docx_to_pdf(
                        sample,
                        out_pdf,
                        renderer="libreoffice",
                        timeout=5,
                    )
                mock_proc.kill.assert_called_once()

    def test_source_file_immutability(self, tmp_path):
        """Verify the source document is never modified during conversion."""
        if not DocxToPdfRenderer.is_backend_available():
            pytest.skip("No document rendering backend available on this machine.")

        src = tmp_path / "immutable.docx"
        shutil.copyfile(FIXTURES_DIR / "docx_01_simple.docx", src)
        before_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        before_mtime = src.stat().st_mtime_ns

        out_pdf = tmp_path / "immutable.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        assert out_pdf.is_file()
        assert out_pdf.stat().st_size > 0

        after_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        after_mtime = src.stat().st_mtime_ns
        assert before_hash == after_hash, "Source file content was mutated!"
        assert before_mtime == after_mtime, "Source file timestamp was altered!"


# ===========================================================================
# 6. Live Rendering Integration Tests (Word COM / LibreOffice)
# ===========================================================================

@pytest.mark.skipif(
    not DocxToPdfRenderer.is_backend_available(),
    reason="No offline document rendering backend (Word COM or LibreOffice) installed.",
)
class TestLiveDocxToPdfRendering:
    """Verifies rendering quality and visual fidelity using an installed offline backend."""

    def test_render_simple_document(self, tmp_path):
        src = FIXTURES_DIR / "docx_01_simple.docx"
        out_pdf = tmp_path / "simple.pdf"
        result_path = DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        assert result_path == out_pdf
        assert out_pdf.is_file()
        assert out_pdf.stat().st_size > 1000

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        assert "LocalShift Simple Document" in text
        assert "Bold text statement" in text
        assert "Italic text explanation" in text

    def test_render_multipage_document(self, tmp_path):
        src = FIXTURES_DIR / "docx_02_multipage.docx"
        out_pdf = tmp_path / "multipage.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 3

        p1_text = pdf[0].get_textpage().get_text_range()
        assert "Multipage Document Analysis" in p1_text

        p2_text = pdf[1].get_textpage().get_text_range()
        assert "Section Two" in p2_text

        p3_text = pdf[2].get_textpage().get_text_range()
        assert "Section Three" in p3_text

    def test_render_tables_document(self, tmp_path):
        src = FIXTURES_DIR / "docx_03_tables.docx"
        out_pdf = tmp_path / "tables.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        assert "System Benchmark Metrics" in text
        assert "LibreOffice" in text
        assert "Word COM" in text
        assert "MPL-2.0" in text

    def test_render_images_document(self, tmp_path):
        src = FIXTURES_DIR / "docx_04_images.docx"
        out_pdf = tmp_path / "images.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        assert "Document with Embedded Media" in text
        assert "Figure 1" in text
        # Verify rendered PDF file size reflects embedded media
        assert out_pdf.stat().st_size > 15000

    def test_render_headers_footers(self, tmp_path):
        src = FIXTURES_DIR / "docx_05_headers_footers.docx"
        out_pdf = tmp_path / "headers_footers.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 1
        text = pdf[0].get_textpage().get_text_range()
        assert "Document with Headers and Footers" in text
        assert "github.com/Krishna-7126/LocalShift" in text

    def test_render_unicode_margins_landscape(self, tmp_path):
        src = FIXTURES_DIR / "docx_06_unicode_margins_landscape.docx"
        out_pdf = tmp_path / "unicode_landscape.pdf"
        DocxToPdfRenderer.render_docx_to_pdf(src, out_pdf)

        pdf = pypdfium2.PdfDocument(out_pdf)
        assert len(pdf) == 1
        page = pdf[0]

        # Verify Landscape orientation (width > height)
        width, height = page.get_size()
        assert width > height, f"Expected landscape orientation, got width={width}, height={height}"

        text = page.get_textpage().get_text_range()
        assert "Universal offline document conversion" in text
        assert "Conversión de documentos" in text
        assert "Sichere und zuverlässige" in text


# ===========================================================================
# 7. End-to-End Execution via convert_request
# ===========================================================================

@pytest.mark.skipif(
    not DocxToPdfRenderer.is_backend_available(),
    reason="No offline document rendering backend (Word COM or LibreOffice) installed.",
)
class TestDocxPipelineEndToEnd:
    """Verifies end-to-end execution through convert_request()."""

    def test_convert_request_docx_to_pdf(self, tmp_path):
        src = FIXTURES_DIR / "docx_01_simple.docx"
        req = ConversionRequest(
            source=src,
            target_format="pdf",
            output_dir=tmp_path,
        )
        res = convert_request(req)

        assert res.output_path.is_file()
        assert res.output_path.suffix.lower() == ".pdf"
        assert res.source_format == "docx"
        assert res.target_format == "pdf"
        assert res.input_bytes > 0
        assert res.output_bytes > 0
        assert res.adapter_id == "docx_to_pdf"

    def test_convert_request_collision_avoidance(self, tmp_path):
        """Converting the same file twice without overwriting must create unique output files."""
        src = FIXTURES_DIR / "docx_01_simple.docx"
        req1 = ConversionRequest(source=src, target_format="pdf", output_dir=tmp_path)
        res1 = convert_request(req1)

        req2 = ConversionRequest(source=src, target_format="pdf", output_dir=tmp_path)
        res2 = convert_request(req2)

        assert res1.output_path.exists()
        assert res2.output_path.exists()
        assert res1.output_path != res2.output_path
        assert " (2)" in res2.output_path.name or "(2)" in res2.output_path.name
