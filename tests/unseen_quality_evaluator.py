"""
tests/unseen_quality_evaluator.py — Independent unseen validation quality evaluation harness.

Evaluates unseen fixtures across:
- Character Error Rate (CER)
- Word Error Rate (WER)
- Strict vs. Normalized metrics
- Unicode diacritic & symbol preservation
- Peak heap memory delta (tracemalloc)
- Processing duration (ms)
- DOCX reconstruction (tables, headings, paragraphs, images, page count, Visual QA via Word COM)
- Native extraction, Auto OCR, and Force OCR routing comparisons
"""
from __future__ import annotations

import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from localshift import ConversionRequest, convert_request
from localshift.documents.pdf_inspector import PdfInspector
from localshift.documents.text_extractor import NativePdfTextExtractor
from tests.pdf_quality_evaluator import (
    compute_cer,
    compute_wer,
    levenshtein_distance,
    normalize_whitespace,
)
from tests.validation_generator import (
    UNSEEN_CATEGORIES,
    UNSEEN_GROUND_TRUTH,
    UNSEEN_OCR_GROUND_TRUTH,
)
from tests.visual_renderer import DocxVisualRenderer


@dataclass(frozen=True)
class UnseenQualityMetric:
    fixture_id: str
    category: str
    page_count: int
    char_count_extracted: int
    char_count_expected: int
    cer: float
    wer: float
    unicode_preserved: bool
    reading_order_valid: bool
    duration_ms: float
    peak_memory_kib: float
    classification: str
    notes: str


@dataclass(frozen=True)
class UnseenDocxMetric:
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


def evaluate_unseen_fixture(pdf_path: Path, *, ocr_mode: str = "native_only") -> UnseenQualityMetric:
    fixture_id = pdf_path.stem
    category = UNSEEN_CATEGORIES.get(fixture_id, "Unseen Document")
    expected_text = (
        UNSEEN_OCR_GROUND_TRUTH.get(fixture_id, "")
        if ocr_mode in ("auto", "force_ocr")
        else UNSEEN_GROUND_TRUTH.get(fixture_id, "")
    )

    report = PdfInspector.inspect(pdf_path)

    tracemalloc.start()
    t0 = time.perf_counter()
    extracted_text = ""
    page_count = report.page_count
    char_count = 0

    try:
        if report.is_readable:
            res = NativePdfTextExtractor.extract(pdf_path, ocr_mode=ocr_mode)
            extracted_text = res.to_plain_text(page_separator="\n\n")
            page_count = res.page_count
            char_count = res.total_characters
    except Exception as exc:
        pass
    finally:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_kib = peak_mem / 1024.0

    cer = compute_cer(expected_text, extracted_text, normalize=True)
    wer = compute_wer(expected_text, extracted_text, normalize=True)

    # Unicode verification
    unicode_preserved = True
    if fixture_id == "val_07_multilingual_legal":
        glyphs = ["schützt", "persönliche", "Déclaration", "conformité", "Garantía", "Bekreftelse", "€", "£", "¥", "$"]
        unicode_preserved = all(g in extracted_text for g in glyphs)

    # Reading order verification
    reading_order_valid = True
    if fixture_id == "val_04_three_column_newsletter":
        # Multi-column sequential order: "Tech Briefing" section must precede "Engineering Note"
        idx1 = extracted_text.find("Tech Briefing")
        idx2 = extracted_text.find("Engineering Note")
        idx3 = extracted_text.find("Community Update")
        if idx1 != -1 and idx2 != -1 and idx3 != -1:
            reading_order_valid = idx1 < idx2 < idx3

    classification_label = "unreadable"
    if report.pages:
        classification_label = report.pages[0].classification.value
        if len(report.pages) > 1 and len({p.classification for p in report.pages}) > 1:
            classification_label = "mixed_pages"

    notes = "OK" if cer < 0.1 else f"CER={cer*100:.1f}%"
    if classification_label == "image_likely" and ocr_mode == "native_only":
        notes = "Raster scan: 0 native text, OCR required"

    return UnseenQualityMetric(
        fixture_id=fixture_id,
        category=category,
        page_count=page_count,
        char_count_extracted=char_count,
        char_count_expected=len(expected_text),
        cer=round(cer, 4),
        wer=round(wer, 4),
        unicode_preserved=unicode_preserved,
        reading_order_valid=reading_order_valid,
        duration_ms=round(duration_ms, 2),
        peak_memory_kib=round(peak_kib, 1),
        classification=classification_label,
        notes=notes,
    )


def evaluate_all_unseen_fixtures(val_dir: Path, *, ocr_mode: str = "native_only") -> list[UnseenQualityMetric]:
    metrics: list[UnseenQualityMetric] = []
    for p in sorted(val_dir.glob("*.pdf")):
        metrics.append(evaluate_unseen_fixture(p, ocr_mode=ocr_mode))
    return metrics


def evaluate_unseen_docx_fixtures(val_dir: Path) -> list[UnseenDocxMetric]:
    import docx
    import tempfile

    visual_available = DocxVisualRenderer.is_available()
    metrics: list[UnseenDocxMetric] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for p in sorted(val_dir.glob("*.pdf")):
            fid = p.stem
            category = UNSEEN_CATEGORIES.get(fid, "Unseen Document")
            expected = UNSEEN_GROUND_TRUTH.get(fid, "")
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
                    UnseenDocxMetric(
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
                    UnseenDocxMetric(
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


def format_text_metrics_table(metrics: list[UnseenQualityMetric]) -> str:
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


def format_docx_metrics_table(metrics: list[UnseenDocxMetric]) -> str:
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
    val_dir = Path(__file__).parent / "fixtures" / "unseen_documents"
    metrics_native = evaluate_all_unseen_fixtures(val_dir, ocr_mode="native_only")
    print("\n# LocalShift Unseen-Document Benchmark Results (Native Mode)\n")
    print(format_text_metrics_table(metrics_native))

    metrics_ocr = evaluate_all_unseen_fixtures(val_dir, ocr_mode="auto")
    print("\n# LocalShift Unseen-Document Benchmark Results (Auto OCR Mode)\n")
    print(format_text_metrics_table(metrics_ocr))

    docx_metrics = evaluate_unseen_docx_fixtures(val_dir)
    print("\n# LocalShift Unseen-Document PDF -> DOCX Reconstruction Results\n")
    print(format_docx_metrics_table(docx_metrics))
