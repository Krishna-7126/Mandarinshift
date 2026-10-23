"""
tests/pdf_quality_evaluator.py — Reproducible extraction quality and reliability harness.

Calculates:
- Character Error Rate (CER) = Levenshtein(reference_chars, hyp_chars) / len(reference_chars)
- Word Error Rate (WER) = Levenshtein(reference_words, hyp_words) / len(reference_words)
- Strict vs. Normalized error rates
- Unicode symbol and diacritic preservation
- Peak heap memory delta (via tracemalloc)
- Extraction duration (ms)
- Layout reading-order flags
"""
from __future__ import annotations

import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Ensure project root and src are on sys.path for direct CLI execution
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from localshift.documents.pdf_inspector import PdfInspector
from localshift.documents.text_extractor import NativePdfTextExtractor
from tests.benchmark_generator import GROUND_TRUTH_TEXT


def levenshtein_distance(seq1: Sequence, seq2: Sequence) -> int:
    """Compute the minimum edit distance between two sequences (characters or words)."""
    m, n = len(seq1), len(seq2)
    if m == 0:
        return n
    if n == 0:
        return m

    # O(n) space DP table
    prev_row = list(range(n + 1))
    for i, c1 in enumerate(seq1, 1):
        curr_row = [i] + [0] * n
        for j, c2 in enumerate(seq2, 1):
            cost = 0 if c1 == c2 else 1
            curr_row[j] = min(
                curr_row[j - 1] + 1,      # Insertion
                prev_row[j] + 1,          # Deletion
                prev_row[j - 1] + cost,   # Substitution
            )
        prev_row = curr_row
    return prev_row[n]


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace without removing punctuation, symbols, or language characters.

    Replaces CRLF, tabs, and runs of horizontal spaces with single spaces,
    and strips leading/trailing space.
    """
    return " ".join(text.split())


def compute_cer(reference: str, hypothesis: str, *, normalize: bool = True) -> float:
    """Compute Character Error Rate (CER).

    Formula: Levenshtein(ref_chars, hyp_chars) / len(ref_chars)
    """
    ref = normalize_whitespace(reference) if normalize else reference
    hyp = normalize_whitespace(hypothesis) if normalize else hypothesis

    if not ref:
        return 0.0 if not hyp else 1.0

    dist = levenshtein_distance(ref, hyp)
    return dist / len(ref)


def compute_wer(reference: str, hypothesis: str, *, normalize: bool = True) -> float:
    """Compute Word Error Rate (WER).

    Formula: Levenshtein(ref_words, hyp_words) / len(ref_words)
    """
    ref_norm = normalize_whitespace(reference) if normalize else reference
    hyp_norm = normalize_whitespace(hypothesis) if normalize else hypothesis

    ref_words = ref_norm.split()
    hyp_words = hyp_norm.split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    dist = levenshtein_distance(ref_words, hyp_words)
    return dist / len(ref_words)


@dataclass(frozen=True)
class QualityMetric:
    """Measured quality, memory, and performance metrics for a single document."""
    fixture_id: str
    category: str
    page_count: int
    char_count_extracted: int
    char_count_ground_truth: int
    cer: float
    wer: float
    cer_strict: float
    wer_strict: float
    unicode_preserved: bool
    reading_order_valid: bool
    duration_ms: float
    peak_memory_kib: float
    classification: str
    warnings: tuple[str, ...]
    notes: str


BENCHMARK_CATEGORIES: dict[str, str] = {
    "doc_01_simple_digital": "1. Simple digital PDF",
    "doc_02_multipage_digital": "2. Multipage digital PDF",
    "doc_03_multicolumn": "4. Multi-column document (sequential)",
    "doc_04_table": "6. Digital PDF containing tables",
    "doc_05_english_scan": "7. Image-only scanned PDF (English)",
    "doc_06_hindi_scan": "7. Image-only scanned PDF (Hindi)",
    "doc_07_mixed_pages": "8. Mixed digital-text and scanned pages",
    "doc_08_rotated_page": "9. Rotated pages (90 deg)",
    "doc_09_corrupt": "11. Corrupt or truncated PDF",
    "doc_10_encrypted": "12. Password-protected PDF",
    "doc_11_unicode_digital": "3. Unicode & multilingual text",
    "doc_12_hierarchy": "5. Heading & paragraph hierarchy",
    "doc_13_empty": "10. Empty or nearly empty PDF",
    "doc_14_interleaved_multicolumn": "4. Multi-column document (interleaved)",
}

OCR_GROUND_TRUTH_TEXT: dict[str, str] = {
    **GROUND_TRUTH_TEXT,
    "doc_05_english_scan": (
        "SCANNED INVOICE (ENGLISH)\n"
        "Invoice Number: INV-2026-001\n"
        "Customer: Tangerine Workflow Alternative\n"
        "Amount Due: $0.00 (Open Source)"
    ),
    "doc_06_hindi_scan": (
        "LocalShift Hindi Document Scan\n"
        "नमस्ते दुनिया (Hello World in Hindi)\n"
        "यह एक हिंदी दस्तावेज़ परीक्षण है।"
    ),
    "doc_07_mixed_pages": (
        "Page 1: Digital Summary Report\n"
        "LocalShift engine supports mixed-content documents.\n\n"
        "SCANNED INVOICE (ENGLISH)\n"
        "Invoice Number: INV-2026-001\n"
        "Customer: Tangerine Workflow Alternative\n"
        "Amount Due: $0.00 (Open Source)"
    ),
}


def evaluate_fixture(pdf_path: Path, *, ocr_mode: str = "native_only") -> QualityMetric:
    """Run full quality and resource evaluation on a benchmark PDF fixture."""
    fixture_id = pdf_path.stem
    category = BENCHMARK_CATEGORIES.get(fixture_id, "Unknown category")
    expected_text = (
        OCR_GROUND_TRUTH_TEXT.get(fixture_id, "")
        if ocr_mode in ("auto", "force_ocr")
        else GROUND_TRUTH_TEXT.get(fixture_id, "")
    )

    # 1. Inspection analysis
    report = PdfInspector.inspect(pdf_path)

    # 2. Extraction under tracemalloc
    tracemalloc.start()
    t0 = time.perf_counter()
    extracted_text = ""
    extractor_warnings: tuple[str, ...] = ()
    page_count = report.page_count
    char_count = 0

    try:
        if report.is_readable:
            res = NativePdfTextExtractor.extract(pdf_path, ocr_mode=ocr_mode)
            extracted_text = res.to_plain_text(page_separator="\n\n")
            extractor_warnings = res.warnings
            page_count = res.page_count
            char_count = res.total_characters
    except Exception as exc:
        extractor_warnings = (f"Extraction error: {exc}",)
    finally:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_kib = peak_mem / 1024.0

    # 3. Compute CER / WER
    cer = compute_cer(expected_text, extracted_text, normalize=True)
    wer = compute_wer(expected_text, extracted_text, normalize=True)
    cer_strict = compute_cer(expected_text, extracted_text, normalize=False)
    wer_strict = compute_wer(expected_text, extracted_text, normalize=False)

    # 4. Unicode preservation check
    unicode_preserved = True
    if fixture_id == "doc_11_unicode_digital":
        sample_glyphs = ["Café", "naïve", "résumé", "façade", "Übergröße", "Füße", "Año", "niño", "£", "€"]
        unicode_preserved = all(glyph in extracted_text for glyph in sample_glyphs)

    # 5. Reading order check
    reading_order_valid = True
    if fixture_id == "doc_14_interleaved_multicolumn":
        # Interleaved reading order means col 1 line 1 was followed by col 2 line 1
        if "Col 1 Line 1 Col 2 Line 1" in extracted_text or "Col 1 Line 1\nCol 2 Line 1" in extracted_text:
            reading_order_valid = False

    # 6. Primary classification label
    classification_label = "unreadable"
    if report.pages:
        classification_label = report.pages[0].classification.value
        if len(report.pages) > 1 and len({p.classification for p in report.pages}) > 1:
            classification_label = "mixed_pages"

    all_warnings = report.warnings + extractor_warnings

    notes = "OK"
    if not report.is_readable:
        notes = report.error or "Unreadable"
    elif not reading_order_valid:
        notes = "Interleaved stream order causes horizontal text reading"
    elif fixture_id in ("doc_05_english_scan", "doc_06_hindi_scan"):
        notes = "Raster scan: 0 native text, OCR required"
    elif fixture_id == "doc_13_empty":
        notes = "Blank page: 0 text objects, classified as empty_or_unknown"

    return QualityMetric(
        fixture_id=fixture_id,
        category=category,
        page_count=page_count,
        char_count_extracted=char_count,
        char_count_ground_truth=len(expected_text),
        cer=round(cer, 4),
        wer=round(wer, 4),
        cer_strict=round(cer_strict, 4),
        wer_strict=round(wer_strict, 4),
        unicode_preserved=unicode_preserved,
        reading_order_valid=reading_order_valid,
        duration_ms=round(duration_ms, 2),
        peak_memory_kib=round(peak_kib, 1),
        classification=classification_label,
        warnings=all_warnings,
        notes=notes,
    )


def evaluate_all_fixtures(fixtures_dir: Path) -> list[QualityMetric]:
    """Evaluate all benchmark PDF fixtures in fixtures_dir sorted by name."""
    metrics: list[QualityMetric] = []
    for p in sorted(fixtures_dir.glob("*.pdf")):
        metrics.append(evaluate_fixture(p))
    return metrics


def format_markdown_table(metrics: list[QualityMetric]) -> str:
    """Format evaluation metrics as a GitHub Flavored Markdown table."""
    lines = [
        "| Fixture | Category | Pages | Chars Extr. | CER | WER | Unicode | Reading Order | Peak Mem (KiB) | Time (ms) | Classification | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        uni_str = "PASS" if m.unicode_preserved else "FAIL"
        ro_str = "PASS" if m.reading_order_valid else "NON-LINEAR"
        cer_pct = f"{m.cer * 100:.1f}%"
        wer_pct = f"{m.wer * 100:.1f}%"
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.page_count} | {m.char_count_extracted} | {cer_pct} | {wer_pct} | {uni_str} | {ro_str} | {m.peak_memory_kib} | {m.duration_ms} | `{m.classification}` | {m.notes} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    fixtures_dir = Path(__file__).parent / "fixtures" / "documents"
    metrics = evaluate_all_fixtures(fixtures_dir)
    print("\n# LocalShift PDF Quality & Reliability Benchmark Results\n")
    print(format_markdown_table(metrics))
