"""
tests/test_pdf_extraction.py — Comprehensive tests for PDF inspection,
native text extraction, and PDF-to-TXT adapter (LS-BE-006B).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from localshift.converter import (
    ConversionCancelledError,
    ConversionFailedError,
    ConversionRequest,
    InvalidInputError,
    convert_request,
)
from localshift.documents.adapter import PdfDocumentAdapter
from localshift.documents.pdf_inspector import (
    PageContentClassification,
    PdfInspectionReport,
    PdfInspector,
)
from localshift.documents.text_extractor import (
    DocumentExtractionResult,
    NativePdfTextExtractor,
)
from localshift.formats import input_format, output_formats_for, route_supported, sniff_format
from localshift.planner import FindingCode, plan_route, validate_preflight
from localshift.registry import default_registry
from tests.benchmark_generator import _build_simple_pdf_bytes

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "documents"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_text(s: str) -> str:
    """Normalize whitespace for determinism in assertions without hiding word order."""
    return " ".join(s.split())


def _install_partially_unreadable_pdfium(monkeypatch):
    class FakeTextPage:
        def __init__(self, unreadable: bool):
            self.unreadable = unreadable

        def get_text_range(self):
            if self.unreadable:
                raise RuntimeError("simulated text extraction failure")
            return "Readable text from page one."

    class FakePage:
        def __init__(self, unreadable: bool):
            self.unreadable = unreadable

        def get_textpage(self):
            return FakeTextPage(self.unreadable)

    class FakeDocument:
        def __init__(self):
            self.pages = (FakePage(False), FakePage(True))

        def __len__(self):
            return len(self.pages)

        def __getitem__(self, index):
            return self.pages[index]

        def close(self):
            pass

    fake_pdfium = ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = lambda path: FakeDocument()
    fake_pdfium.PdfiumError = RuntimeError
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)


# ---------------------------------------------------------------------------
# 1. PDF Inspection Tests
# ---------------------------------------------------------------------------

class TestPdfInspector:
    def test_inspect_simple_digital_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert isinstance(report, PdfInspectionReport)
        assert report.page_count == 1
        assert report.is_readable is True
        assert report.is_encrypted is False
        assert report.error is None
        assert report.total_characters > 100

        page = report.pages[0]
        assert page.page_number == 1
        assert page.width_points == pytest.approx(612.0, rel=1e-2)
        assert page.height_points == pytest.approx(792.0, rel=1e-2)
        assert page.rotation == 0
        assert page.classification is PageContentClassification.TEXT_PRESENT
        assert "LocalShift Document Engine" in page.extracted_text_preview
        assert len(page.warnings) == 0

    def test_inspect_multipage_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 3
        assert report.is_readable is True
        assert len(report.pages) == 3
        for idx, page in enumerate(report.pages, start=1):
            assert page.page_number == idx
            assert page.classification is PageContentClassification.TEXT_PRESENT
            assert page.character_count > 50

    def test_inspect_multicolumn_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_03_multicolumn.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 1
        assert report.pages[0].classification is PageContentClassification.TEXT_PRESENT
        assert "Column 1 Headline" in report.pages[0].extracted_text_preview

    def test_inspect_table_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_04_table.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 1
        assert report.pages[0].classification is PageContentClassification.TEXT_PRESENT
        assert "Item ID" in report.pages[0].extracted_text_preview

    def test_inspect_scanned_image_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 1
        assert report.is_readable is True
        assert report.total_characters == 0
        page = report.pages[0]
        assert page.classification is PageContentClassification.IMAGE_LIKELY
        assert any("no native extractable text" in w.lower() for w in page.warnings)

    def test_inspect_hindi_scanned_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_06_hindi_scan.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 1
        assert report.pages[0].classification is PageContentClassification.IMAGE_LIKELY
        assert report.total_characters == 0

    def test_inspect_mixed_pages_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_07_mixed_pages.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 2
        assert report.pages[0].classification is PageContentClassification.TEXT_PRESENT
        assert report.pages[1].classification is PageContentClassification.IMAGE_LIKELY
        assert report.has_native_text is True
        assert report.candidate_for_ocr is True

    def test_inspect_rotated_page_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_08_rotated_page.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.page_count == 1
        page = report.pages[0]
        assert page.rotation == 90
        assert page.classification is PageContentClassification.TEXT_PRESENT
        assert any("rotation: 90" in w for w in page.warnings)

    def test_inspect_corrupt_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_09_corrupt.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.is_readable is False
        assert report.page_count == 0
        assert report.error is not None
        assert "corrupt" in report.error.lower() or "data format" in report.error.lower()

    def test_inspect_encrypted_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_10_encrypted.pdf"
        report = PdfInspector.inspect(pdf_path)

        assert report.is_encrypted is True
        assert report.is_readable is False
        assert "password" in (report.error or "").lower()

    def test_inspect_missing_file_returns_unreadable_report(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.pdf"
        report = PdfInspector.inspect(missing)
        assert report.is_readable is False
        assert "not found" in (report.error or "").lower()


# ---------------------------------------------------------------------------
# 2. Native Text Extraction Tests
# ---------------------------------------------------------------------------

class TestNativeTextExtractor:
    def test_extract_simple_digital_text(self):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        result = NativePdfTextExtractor.extract(pdf_path)

        assert isinstance(result, DocumentExtractionResult)
        assert result.page_count == 1
        assert len(result.pages) == 1

        p1 = result.pages[0]
        assert p1.page_number == 1
        assert "LocalShift Document Engine" in p1.text
        assert "born-digital PDF document" in p1.text
        assert p1.character_count == len(p1.text)

    def test_extract_multipage_text_and_plain_text_join(self):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        result = NativePdfTextExtractor.extract(pdf_path)

        assert result.page_count == 3
        assert "Page 1 of 3" in result.pages[0].text
        assert "Page 2 of 3" in result.pages[1].text
        assert "Page 3 of 3" in result.pages[2].text

        full = result.to_plain_text(page_separator="\n--- PAGE {page} ---\n")
        assert "--- PAGE 1 ---" in full
        assert "--- PAGE 2 ---" in full
        assert "--- PAGE 3 ---" in full

    def test_extract_multicolumn_preserves_content(self):
        pdf_path = FIXTURES_DIR / "doc_03_multicolumn.pdf"
        result = NativePdfTextExtractor.extract(pdf_path)

        text = result.pages[0].text
        assert "Column 1 Headline" in text
        assert "Column 2 Headline" in text

    def test_extract_table_content(self):
        pdf_path = FIXTURES_DIR / "doc_04_table.pdf"
        result = NativePdfTextExtractor.extract(pdf_path)

        text = result.pages[0].text
        assert "Item ID" in text
        assert "LS-001" in text
        assert "Image Converter" in text

    def test_extract_scanned_pdf_produces_warning(self):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        result = NativePdfTextExtractor.extract(pdf_path)

        assert result.total_characters == 0
        assert len(result.warnings) > 0
        assert any("scan" in w.lower() for w in result.warnings)

    def test_extract_cancellation_callback(self):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        call_count = 0

        def cancel_check():
            nonlocal call_count
            call_count += 1
            return call_count > 1  # Cancel on second page check

        with pytest.raises(ConversionCancelledError):
            NativePdfTextExtractor.extract(pdf_path, cancel_check=cancel_check)

    def test_extract_max_pages_limit(self):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"  # 3 pages
        with pytest.raises(InvalidInputError, match="exceeding the limit"):
            NativePdfTextExtractor.extract(pdf_path, max_pages=2)

    def test_extract_preserves_readable_and_unreadable_pages(self, tmp_path: Path, monkeypatch):
        _install_partially_unreadable_pdfium(monkeypatch)
        pdf_path = tmp_path / "mixed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")

        result = NativePdfTextExtractor.extract(pdf_path)

        assert result.page_count == 2
        assert result.pages[0].text == "Readable text from page one."
        assert result.pages[0].classification is PageContentClassification.MIXED_OR_UNCERTAIN
        assert result.pages[1].text == ""
        assert result.pages[1].classification is PageContentClassification.UNREADABLE
        assert "simulated text extraction failure" in result.pages[1].warnings[0]

    def test_extract_unicode_digital_pdf(self, tmp_path: Path):
        # Synthesize a born-digital PDF containing non-ASCII / Unicode Latin text
        unicode_text = "LocalShift Tëst: Café résumé naïve façade. 100€ — OK."
        raw_pdf = _build_simple_pdf_bytes([unicode_text])
        p = tmp_path / "unicode.pdf"
        p.write_bytes(raw_pdf)

        result = NativePdfTextExtractor.extract(p)
        assert result.page_count == 1
        # Check that characters are present
        assert "LocalShift" in result.pages[0].text


# ---------------------------------------------------------------------------
# 3. PDF to TXT Adapter & Request-Based Execution
# ---------------------------------------------------------------------------

class TestPdfToTxtConversion:
    def test_partial_page_extraction_failure_leaves_no_output(self, tmp_path: Path, monkeypatch):
        _install_partially_unreadable_pdfium(monkeypatch)
        pdf_path = tmp_path / "mixed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        output_dir = tmp_path / "output"
        request = ConversionRequest(source=pdf_path, target_format="txt", output_dir=output_dir)

        with pytest.raises(ConversionFailedError, match=r"page\(s\): 2"):
            convert_request(request)

        assert list(output_dir.iterdir()) == []

    def test_adapter_registered_in_default_registry(self):
        adapter = default_registry.get_adapter("pdf", "txt")
        assert adapter is not None
        assert adapter.adapter_id == "pdf_native_text"
        assert default_registry.can_convert("pdf", "txt") is True

    def test_format_sniffing_pdf(self):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        assert sniff_format(pdf_path) == "pdf"
        assert input_format(pdf_path) == "pdf"

    def test_capability_discovery_pdf_to_txt(self):
        assert route_supported("pdf", "txt") is True
        assert route_supported("pdf", "jpeg") is True
        assert route_supported("pdf", "xyz") is False
        assert "txt" in output_formats_for(FIXTURES_DIR / "doc_01_simple_digital.pdf")

    def test_convert_simple_pdf_to_txt(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        assert result.target_format == "txt"
        assert result.output_path.exists()
        assert result.output_path.suffix == ".txt"
        assert result.output_path.stat().st_size > 0

        content = result.output_path.read_text(encoding="utf-8")
        assert "LocalShift Document Engine" in content
        assert "born-digital PDF document" in content

    def test_convert_multipage_pdf_with_custom_separator(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_02_multipage_digital.pdf"
        sep = "\n\n=== SECTION PAGE {page} ===\n\n"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
            options={"page_separator": sep},
        )
        result = convert_request(req)

        assert result.output_path.exists()
        content = result.output_path.read_text(encoding="utf-8")
        assert "=== SECTION PAGE 1 ===" in content
        assert "=== SECTION PAGE 2 ===" in content
        assert "=== SECTION PAGE 3 ===" in content

    def test_convert_scanned_pdf_succeeds_with_warnings(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        assert result.output_path.exists()
        assert len(result.warnings) > 0
        assert any("scan" in w.lower() for w in result.warnings)

    def test_convert_corrupt_pdf_fails_safely(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_09_corrupt.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
        )
        with pytest.raises((InvalidInputError, ConversionFailedError)):
            convert_request(req)

    def test_convert_encrypted_pdf_fails_safely(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_10_encrypted.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
        )
        with pytest.raises(InvalidInputError, match="[Pp]assword"):
            convert_request(req)

    def test_collision_safe_output(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        # Pre-create the target file
        existing = tmp_path / "doc_01_simple_digital.txt"
        existing.write_text("existing content", encoding="utf-8")

        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
        )
        result = convert_request(req)

        # Pre-existing file is not overwritten
        assert existing.read_text(encoding="utf-8") == "existing content"
        # New output is collision-avoided (Windows style: doc_01_simple_digital (2).txt)
        assert result.output_path != existing
        assert result.output_path.name == "doc_01_simple_digital (2).txt"
        assert result.output_path.exists()

    def test_plan_route_pdf_to_txt(self):
        plan = plan_route("pdf", "txt")
        assert plan.route_supported is True
        assert plan.adapter_id == "pdf_native_text"
        assert plan.is_ready is True
        assert len(plan.applicable_options) == 4
        option_names = [opt.name for opt in plan.applicable_options]
        assert "page_separator" in option_names
        assert "ocr_mode" in option_names
        assert "ocr_dpi" in option_names
        assert "ocr_language" in option_names

    def test_plan_route_pdf_to_docx_supported(self):
        plan = plan_route("pdf", "docx")
        assert plan.route_supported is True
        assert plan.adapter_id == "pdf_native_text"
        assert plan.is_ready is True
        option_names = [opt.name for opt in plan.applicable_options]
        assert "ocr_mode" in option_names
        assert "ocr_dpi" in option_names
        assert "extract_images" in option_names

    def test_plan_route_pdf_to_unsupported_format(self):
        plan = plan_route("pdf", "xlsx")
        assert plan.route_supported is False
        assert plan.is_ready is False

    def test_preflight_validation_pdf_to_txt(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        req = ConversionRequest(source=pdf_path, target_format="txt", output_dir=tmp_path)
        findings = validate_preflight(req)
        # Should have no blocking errors
        assert not any(f.blocks_execution for f in findings)
