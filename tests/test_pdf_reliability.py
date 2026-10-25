"""
tests/test_pdf_reliability.py — Automated reliability, quality metrics,
and benchmark corpus verification (LS-BE-006C).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from localshift.documents.pdf_inspector import PageContentClassification, PdfInspector
from localshift.documents.text_extractor import NativePdfTextExtractor
from tests.benchmark_generator import GROUND_TRUTH_TEXT
from tests.pdf_quality_evaluator import (
    compute_cer,
    compute_wer,
    evaluate_all_fixtures,
    evaluate_fixture,
    levenshtein_distance,
    normalize_whitespace,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "documents"


# ---------------------------------------------------------------------------
# 1. Metric Calculation Tests
# ---------------------------------------------------------------------------

class TestMetricCalculations:
    def test_levenshtein_distance_exact_matches(self):
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("hello", "hello") == 0
        assert levenshtein_distance(["word1", "word2"], ["word1", "word2"]) == 0

    def test_levenshtein_distance_insertions_deletions_substitutions(self):
        assert levenshtein_distance("kitten", "sitting") == 3
        assert levenshtein_distance("", "abc") == 3
        assert levenshtein_distance("abc", "") == 3

    def test_compute_cer_clean_and_degraded(self):
        assert compute_cer("hello world", "hello world") == 0.0
        assert compute_cer("", "") == 0.0
        assert compute_cer("", "extra text") == 1.0
        # 1 substitution in 10 characters -> 0.1
        assert compute_cer("0123456789", "012345678X", normalize=False) == pytest.approx(0.1)

    def test_compute_wer_clean_and_degraded(self):
        assert compute_wer("the quick brown fox", "the quick brown fox") == 0.0
        assert compute_wer("", "") == 0.0
        assert compute_wer("", "word") == 1.0
        # 1 replacement in 4 words -> 0.25
        assert compute_wer("the quick brown fox", "the fast brown fox") == pytest.approx(0.25)

    def test_normalize_whitespace_preserves_content(self):
        raw = "  Hello \t\t world \r\n\r\n this is \n a test.  "
        assert normalize_whitespace(raw) == "Hello world this is a test."


# ---------------------------------------------------------------------------
# 2. Benchmark Corpus Quality & Error Rates (CER / WER)
# ---------------------------------------------------------------------------

class TestCorpusQualityAndErrorRates:
    def test_doc_01_simple_digital_accuracy(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_01_simple_digital.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.page_count == 1
        assert metric.classification == "text_present"
        assert metric.reading_order_valid is True

    def test_doc_02_multipage_digital_accuracy(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_02_multipage_digital.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.page_count == 3
        assert metric.classification == "text_present"

    def test_doc_03_multicolumn_sequential_accuracy(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_03_multicolumn.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.reading_order_valid is True

    def test_doc_04_table_accuracy(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_04_table.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.char_count_extracted > 100

    def test_doc_11_unicode_digital_preservation(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_11_unicode_digital.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.unicode_preserved is True

    def test_doc_12_hierarchy_accuracy(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_12_hierarchy.pdf")
        assert metric.cer == 0.0
        assert metric.wer == 0.0
        assert metric.char_count_extracted > 200


# ---------------------------------------------------------------------------
# 3. Document Edge Cases, Rotations, and Diagnostics
# ---------------------------------------------------------------------------

class TestCorpusEdgeCasesAndClassification:
    def test_doc_05_scanned_image_diagnostics(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_05_english_scan.pdf")
        assert metric.char_count_extracted == 0
        assert metric.classification == "image_likely"
        assert any("no native" in w.lower() or "scan" in w.lower() for w in metric.warnings)

    def test_doc_06_hindi_scanned_diagnostics(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_06_hindi_scan.pdf")
        assert metric.char_count_extracted == 0
        assert metric.classification == "image_likely"

    def test_doc_07_mixed_pages_classification(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_07_mixed_pages.pdf")
        assert metric.page_count == 2
        assert metric.classification == "mixed_pages"
        assert metric.char_count_extracted > 50

        # Detailed inspector checks
        report = PdfInspector.inspect(FIXTURES_DIR / "doc_07_mixed_pages.pdf")
        assert report.pages[0].classification is PageContentClassification.TEXT_PRESENT
        assert report.pages[1].classification is PageContentClassification.IMAGE_LIKELY
        assert report.has_native_text is True
        assert report.candidate_for_ocr is True

    def test_doc_08_rotated_page_orientation_and_diagnostics(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_08_rotated_page.pdf")
        report = PdfInspector.inspect(FIXTURES_DIR / "doc_08_rotated_page.pdf")
        assert report.pages[0].rotation == 90
        assert any("rotation: 90" in w for w in report.pages[0].warnings)
        # Verify content was extracted
        assert metric.char_count_extracted > 0

    def test_doc_13_truly_empty_page_diagnostics(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_13_empty.pdf")
        assert metric.char_count_extracted == 0
        assert metric.classification == "empty_or_unknown"

        report = PdfInspector.inspect(FIXTURES_DIR / "doc_13_empty.pdf")
        assert report.pages[0].classification is PageContentClassification.EMPTY_OR_UNKNOWN
        assert any("empty" in w.lower() for w in report.pages[0].warnings)

    def test_doc_14_interleaved_multicolumn_reading_order_flag(self):
        metric = evaluate_fixture(FIXTURES_DIR / "doc_14_interleaved_multicolumn.pdf")
        assert metric.reading_order_valid is False
        assert "Interleaved" in metric.notes or "horizontal" in metric.notes


# ---------------------------------------------------------------------------
# 4. Performance, Memory and Resource Bounds
# ---------------------------------------------------------------------------

class TestPerformanceAndResourceBounds:
    def test_all_fixtures_memory_and_latency_bounds(self):
        metrics = evaluate_all_fixtures(FIXTURES_DIR)
        assert len(metrics) == 18

        for m in metrics:
            # Heap delta must be well under 2 MiB (2048 KiB)
            assert m.peak_memory_kib < 2048.0, f"Excessive memory for {m.fixture_id}: {m.peak_memory_kib} KiB"
            # Execution time must be under 500 ms per fixture on local host
            assert m.duration_ms < 500.0, f"Extraction too slow for {m.fixture_id}: {m.duration_ms} ms"
