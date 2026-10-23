"""
tests/test_pdf_ocr.py — Comprehensive tests for offline OCR engine, page rendering,
reading-order reconstruction, per-page routing, and accuracy benchmarks (LS-BE-006D).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from localshift.converter import convert_request
from localshift.documents.adapter import PdfDocumentAdapter
from localshift.documents.ocr import (
    OcrPageResult,
    OcrTextBlock,
    RapidOcrEngine,
    reconstruct_reading_order,
)
from localshift.documents.pdf_inspector import PageContentClassification, PdfInspector
from localshift.documents.renderer import PdfPageRenderer
from localshift.documents.text_extractor import (
    DocumentExtractionResult,
    NativePdfTextExtractor,
    PageTextResult,
)
from localshift.exceptions import ConversionCancelledError, ConversionFailedError, InvalidInputError
from localshift.models import ConversionContext, ConversionRequest
from tests.benchmark_generator import GROUND_TRUTH_TEXT
from tests.pdf_quality_evaluator import (
    OCR_GROUND_TRUTH_TEXT,
    compute_cer,
    compute_wer,
    evaluate_fixture,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "documents"


# ===========================================================================
# 1. OCR Engine & Geometry Unit Tests
# ===========================================================================

class TestOcrEngineFoundation:
    def test_rapid_ocr_available(self):
        assert RapidOcrEngine.is_available() is True
        engine = RapidOcrEngine.get_engine()
        assert engine is not None

    def test_ocr_text_block_geometry(self):
        raw_box = [[10.0, 20.0], [100.0, 20.0], [100.0, 50.0], [10.0, 50.0]]
        block = OcrTextBlock.from_raw_detection(
            raw_box,
            "Sample Headline",
            "0.95",
            page_number=1,
            detection_order=0,
        )
        assert block.text == "Sample Headline"
        assert block.confidence == pytest.approx(0.95)
        assert block.page_number == 1
        assert block.detection_order == 0
        assert block.x_min == 10.0
        assert block.x_max == 100.0
        assert block.y_min == 20.0
        assert block.y_max == 50.0
        assert block.width == 90.0
        assert block.height == 30.0

    def test_reconstruct_reading_order_line_grouping(self):
        # Two words on line 1, one on line 2, given out of order
        blocks = [
            OcrTextBlock.from_raw_detection([[100.0, 10.0], [150.0, 10.0], [150.0, 30.0], [100.0, 30.0]], "World", 0.9, page_number=1, detection_order=1),
            OcrTextBlock.from_raw_detection([[10.0, 50.0], [120.0, 50.0], [120.0, 70.0], [10.0, 70.0]], "Second Line", 0.9, page_number=1, detection_order=2),
            OcrTextBlock.from_raw_detection([[20.0, 12.0], [90.0, 12.0], [90.0, 32.0], [20.0, 32.0]], "Hello", 0.9, page_number=1, detection_order=0),
        ]
        text = reconstruct_reading_order(blocks)
        lines = text.split("\n")
        assert len(lines) == 2
        assert lines[0] == "Hello World"
        assert lines[1] == "Second Line"

    def test_reconstruct_reading_order_empty(self):
        assert reconstruct_reading_order([]) == ""

    def test_ocr_process_blank_image(self):
        # 400x300 pure white canvas
        white_img = np.full((300, 400, 3), 255, dtype=np.uint8)
        res = RapidOcrEngine.process_image(white_img, page_number=1)
        assert res.page_number == 1
        assert res.text == ""
        assert len(res.blocks) == 0
        assert res.mean_confidence == 0.0
        assert len(res.warnings) > 0


# ===========================================================================
# 2. Page Renderer Security and Limits Tests
# ===========================================================================

class TestPdfPageRenderer:
    def test_render_page_dimensions_and_cleanup(self):
        import pypdfium2
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        doc = pypdfium2.PdfDocument(pdf_path)
        try:
            arr = PdfPageRenderer.render_page(doc[0], dpi=150)
            assert isinstance(arr, np.ndarray)
            assert arr.ndim == 3
            assert arr.shape[2] == 3  # RGB
            assert arr.dtype == np.uint8
        finally:
            doc.close()

    def test_render_page_dpi_clamping(self):
        import pypdfium2
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        doc = pypdfium2.PdfDocument(pdf_path)
        try:
            # Below MIN_DPI (72) -> clamped to 72
            arr_low = PdfPageRenderer.render_page(doc[0], dpi=20)
            assert arr_low.shape[0] == 792  # 792 pts at 72 dpi = 792 px
            assert arr_low.shape[1] == 612  # 612 pts at 72 dpi = 612 px
        finally:
            doc.close()

    def test_render_page_pixel_ceiling(self):
        import pypdfium2
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        doc = pypdfium2.PdfDocument(pdf_path)
        try:
            # Force max_pixels limit to 100,000 pixels (roughly 316x316)
            arr = PdfPageRenderer.render_page(doc[0], dpi=300, max_pixels=100_000)
            total_pixels = arr.shape[0] * arr.shape[1]
            assert total_pixels <= 105_000
        finally:
            doc.close()


# ===========================================================================
# 3. Scanned PDF & Routing Integration Tests
# ===========================================================================

class TestPdfOcrExtractionRouting:
    def test_english_scanned_pdf_produces_meaningful_text(self):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        result = NativePdfTextExtractor.extract(pdf_path, ocr_mode="auto")

        assert result.page_count == 1
        assert result.ocr_pages_count == 1
        assert result.total_characters > 80

        page = result.pages[0]
        assert page.ocr_applied is True
        assert page.confidence is not None
        assert page.confidence > 0.70

        text = page.text
        assert "INVOICE" in text.upper()
        assert "2026" in text
        assert "TANGERINE" in text.upper()

    def test_english_scan_accuracy_cer_wer(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_05_english_scan.pdf", ocr_mode="auto")
        assert metric.char_count_extracted > 80
        # CER must be below 10% on clean printed English scan
        assert metric.cer < 0.10, f"CER too high: {metric.cer:.1%}"
        # WER must be below 55%
        assert metric.wer < 0.55, f"WER too high: {metric.wer:.1%}"

    def test_hindi_scan_documented_model_limitation(self):
        """Devanagari script is not bundled in the default ch/en model."""
        result = NativePdfTextExtractor.extract(
            FIXTURES_DIR / "doc_06_hindi_scan.pdf",
            ocr_mode="auto",
        )
        assert result.page_count == 1
        assert result.ocr_pages_count == 1
        # English header is recognized
        assert "LocalShift Hindi Document Scan" in result.pages[0].text
        # Devanagari text is omitted or approximated due to lack of Hindi rec model

    def test_mixed_pages_per_page_routing(self):
        pdf_path = FIXTURES_DIR / "doc_07_mixed_pages.pdf"
        result = NativePdfTextExtractor.extract(pdf_path, ocr_mode="auto")

        assert result.page_count == 2
        p1, p2 = result.pages

        # Page 1: Native digital text
        assert p1.ocr_applied is False
        assert p1.classification is PageContentClassification.TEXT_PRESENT
        assert "Digital Summary Report" in p1.text

        # Page 2: Scanned raster image
        assert p2.ocr_applied is True
        assert p2.classification is PageContentClassification.IMAGE_LIKELY
        assert "INVOICE" in p2.text.upper()

    def test_blank_page_no_hallucinations(self):
        pdf_path = FIXTURES_DIR / "doc_13_empty.pdf"
        result = NativePdfTextExtractor.extract(pdf_path, ocr_mode="auto")

        assert result.page_count == 1
        assert result.ocr_pages_count == 0
        assert result.total_characters == 0
        assert result.pages[0].ocr_applied is False
        assert result.pages[0].classification is PageContentClassification.EMPTY_OR_UNKNOWN
        assert result.to_plain_text() == ""

    def test_force_ocr_mode(self):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        result = NativePdfTextExtractor.extract(pdf_path, ocr_mode="force_ocr")
        assert result.ocr_pages_count == 1
        assert result.pages[0].ocr_applied is True
        assert "LocalShift" in result.pages[0].text

    def test_native_only_mode_skips_ocr(self):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        result = NativePdfTextExtractor.extract(pdf_path, ocr_mode="native_only")
        assert result.ocr_pages_count == 0
        assert result.total_characters == 0
        assert result.pages[0].ocr_applied is False

    def test_invalid_ocr_mode_raises(self):
        pdf_path = FIXTURES_DIR / "doc_01_simple_digital.pdf"
        with pytest.raises(InvalidInputError, match="Invalid ocr_mode"):
            NativePdfTextExtractor.extract(pdf_path, ocr_mode="invalid_mode")


# ===========================================================================
# 4. End-to-End PDF to TXT Adapter Tests
# ===========================================================================

class TestPdfToTxtOcrEndToEnd:
    def test_adapter_convert_scanned_pdf_to_txt(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_05_english_scan.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
            options={"ocr_mode": "auto", "ocr_dpi": 200},
        )
        res = convert_request(req)

        assert res.output_path.exists()
        content = res.output_path.read_text(encoding="utf-8")
        assert "INVOICE" in content.upper()
        assert "INV-2026-001" in content
        assert "Tangerine" in content
        assert any("scan" in w.lower() for w in res.warnings)

    def test_adapter_convert_mixed_pdf_to_txt(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_07_mixed_pages.pdf"
        req = ConversionRequest(
            source=pdf_path,
            target_format="txt",
            output_dir=tmp_path,
            options={"ocr_mode": "auto"},
        )
        res = convert_request(req)

        content = res.output_path.read_text(encoding="utf-8")
        assert "Digital Summary Report" in content
        assert "INVOICE" in content.upper()
        assert "--- Page 1 ---" in content
        assert "--- Page 2 ---" in content

    def test_cancellation_during_ocr_processing(self, tmp_path: Path):
        pdf_path = FIXTURES_DIR / "doc_07_mixed_pages.pdf"
        cancelled = False

        def cancel_check():
            return cancelled

        context = ConversionContext(
            temp_output_path=tmp_path / "temp.txt",
            target_format="txt",
            max_input_bytes=100_000_000,
            _is_cancelled=cancel_check,
        )
        adapter = PdfDocumentAdapter()
        req = ConversionRequest(source=pdf_path, target_format="txt", output_dir=tmp_path)

        # Cancel immediately before execution
        cancelled = True
        with pytest.raises(ConversionCancelledError):
            adapter.convert(req, context)
