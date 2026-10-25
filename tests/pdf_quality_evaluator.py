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

from localshift import ConversionRequest, convert_request
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
    "doc_15_borderless_table": "13. Borderless tables",
    "doc_16_image_caption": "10. Images and captions",
    "doc_17_headers_footers": "11. Headers, footers and page numbers",
    "doc_18_dense_document": "14. Dense documents",
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


def evaluate_all_fixtures(fixtures_dir: Path, *, ocr_mode: str = "native_only") -> list[QualityMetric]:
    """Evaluate all benchmark PDF fixtures in fixtures_dir sorted by name."""
    metrics: list[QualityMetric] = []
    for p in sorted(fixtures_dir.glob("*.pdf")):
        metrics.append(evaluate_fixture(p, ocr_mode=ocr_mode))
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


@dataclass(frozen=True)
class DocxQualityMetric:
    fixture_id: str
    category: str
    tables_count: int
    headings_count: int
    paragraphs_count: int
    images_count: int
    cer: float
    wer: float
    peak_memory_kib: float
    duration_ms: float
    visual_render_status: str
    notes: str


def evaluate_all_docx_fixtures(fixtures_dir: Path) -> list[DocxQualityMetric]:
    import docx
    import tempfile
    from tests.visual_renderer import DocxVisualRenderer

    visual_available = DocxVisualRenderer.is_available()

    metrics: list[DocxQualityMetric] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for p in sorted(fixtures_dir.glob("*.pdf")):
            fid = p.stem
            category = BENCHMARK_CATEGORIES.get(fid, "Standard Document")
            expected = GROUND_TRUTH_TEXT.get(fid, "")
            tracemalloc.start()
            t0 = time.perf_counter()
            try:
                req = ConversionRequest(source=p, target_format="docx", output_dir=tmp_path)
                res = convert_request(req)
                t1 = time.perf_counter()
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                d = docx.Document(res.output_path)
                para_texts = [para.text for para in d.paragraphs if para.text]
                hdgs = [para.text for para in d.paragraphs if para.style.name.startswith("Heading")]
                img_count = len(d.inline_shapes)
                tbl_texts = []
                for t in d.tables:
                    for row in t.rows:
                        tbl_texts.append(" ".join(c.text for c in row.cells))
                all_text = "\n".join(para_texts + tbl_texts)
                norm_hyp = normalize_whitespace(all_text)
                norm_exp = normalize_whitespace(expected)
                cer = levenshtein_distance(norm_exp, norm_hyp) / max(1, len(norm_exp)) if norm_exp else 0.0
                wer = levenshtein_distance(norm_exp.split(), norm_hyp.split()) / max(1, len(norm_exp.split())) if norm_exp else 0.0

                # Visual QA rendering verification
                visual_status = "N/A"
                if visual_available:
                    try:
                        rendered_pdf = tmp_path / f"{fid}_qa_rendered.pdf"
                        DocxVisualRenderer.render_docx_to_pdf(res.output_path, rendered_pdf)
                        import pypdfium2
                        rendered_doc = pypdfium2.PdfDocument(rendered_pdf)
                        pages_rendered = len(rendered_doc)
                        rendered_doc.close()
                        visual_status = f"PASS ({pages_rendered}p)"
                    except Exception as v_err:
                        visual_status = f"FAIL ({v_err})"
                else:
                    visual_status = "Renderer Unavailable"

                metrics.append(
                    DocxQualityMetric(
                        fixture_id=fid,
                        category=category,
                        tables_count=len(d.tables),
                        headings_count=len(hdgs),
                        paragraphs_count=len(para_texts),
                        images_count=img_count,
                        cer=round(cer, 4),
                        wer=round(wer, 4),
                        peak_memory_kib=round(peak / 1024, 1),
                        duration_ms=round((t1 - t0) * 1000, 2),
                        visual_render_status=visual_status,
                        notes="OK" if cer < 0.1 else f"CER={cer*100:.1f}%",
                    )
                )
            except Exception as exc:
                tracemalloc.stop()
                metrics.append(
                    DocxQualityMetric(
                        fixture_id=fid,
                        category=category,
                        tables_count=0,
                        headings_count=0,
                        paragraphs_count=0,
                        images_count=0,
                        cer=1.0,
                        wer=1.0,
                        peak_memory_kib=0.0,
                        duration_ms=0.0,
                        visual_render_status="N/A",
                        notes=f"Rejected: {exc}",
                    )
                )
    return metrics


def format_docx_markdown_table(metrics: list[DocxQualityMetric]) -> str:
    lines = [
        "| Fixture | Category | Tables | Headings | Paragraphs | Images | CER | WER | Visual QA | Mem (KiB) | Time (ms) | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        cer_pct = f"{m.cer * 100:.1f}%"
        wer_pct = f"{m.wer * 100:.1f}%"
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.tables_count} | {m.headings_count} | {m.paragraphs_count} | {m.images_count} | {cer_pct} | {wer_pct} | {m.visual_render_status} | {m.peak_memory_kib} | {m.duration_ms} | {m.notes} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    fixtures_dir = Path(__file__).parent / "fixtures" / "documents"
    metrics_native = evaluate_all_fixtures(fixtures_dir, ocr_mode="native_only")
    print("\n# LocalShift PDF Quality & Reliability Benchmark Results (Native Mode)\n")
    print(format_markdown_table(metrics_native))

    metrics_ocr = evaluate_all_fixtures(fixtures_dir, ocr_mode="auto")
    print("\n# LocalShift PDF Quality & Reliability Benchmark Results (Auto OCR Mode)\n")
    print(format_markdown_table(metrics_ocr))

    docx_metrics = evaluate_all_docx_fixtures(fixtures_dir)
    print("\n# LocalShift PDF -> DOCX Reconstruction Benchmark Results\n")
    print(format_docx_markdown_table(docx_metrics))
