"""
tests/real_world_quality_evaluator.py — Real-world PDF and PDF -> DOCX quality evaluation harness.

Evaluates real-world evaluation fixtures across:
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
from tests.real_world_generator import (
    REAL_WORLD_CATEGORIES,
    REAL_WORLD_GROUND_TRUTH,
    REAL_WORLD_OCR_GROUND_TRUTH,
    generate_real_world_fixtures,
)
from tests.visual_renderer import DocxVisualRenderer


@dataclass(frozen=True)
class RealWorldQualityMetric:
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
class RealWorldDocxMetric:
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


def evaluate_real_world_fixture(pdf_path: Path, *, ocr_mode: str = "native_only") -> RealWorldQualityMetric:
    fixture_id = pdf_path.stem
    category = REAL_WORLD_CATEGORIES.get(fixture_id, "Real-World Document")
    expected_text = (
        REAL_WORLD_OCR_GROUND_TRUTH.get(fixture_id, "")
        if ocr_mode in ("auto", "force_ocr")
        else REAL_WORLD_GROUND_TRUTH.get(fixture_id, "")
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
    except Exception:
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
    if fixture_id == "rw_06_multilingual_trade_treaty":
        glyphs = ["Sprachbestimmungen", "deutscher", "ordnungsgemäße", "Erfüllung", "Français", "décisions", "Cláusulas", "Español", "vigentes"]
        unicode_preserved = all(g in extracted_text for g in glyphs)

    # Reading order verification
    reading_order_valid = True
    if fixture_id == "rw_03_research_paper_multicolumn":
        idx1 = extracted_text.find("1. Introduction")
        idx2 = extracted_text.find("2. Methodology")
        idx3 = extracted_text.find("3. Experimental Results")
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

    return RealWorldQualityMetric(
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


def evaluate_all_real_world_fixtures(rw_dir: Path, *, ocr_mode: str = "native_only") -> list[RealWorldQualityMetric]:
    metrics: list[RealWorldQualityMetric] = []
    for p in sorted(rw_dir.glob("*.pdf")):
        metrics.append(evaluate_real_world_fixture(p, ocr_mode=ocr_mode))
    return metrics


def evaluate_real_world_docx_fixtures(rw_dir: Path) -> list[RealWorldDocxMetric]:
    import docx
    import tempfile

    visual_available = DocxVisualRenderer.is_available()
    metrics: list[RealWorldDocxMetric] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for p in sorted(rw_dir.glob("*.pdf")):
            fid = p.stem
            category = REAL_WORLD_CATEGORIES.get(fid, "Real-World Document")
            expected = REAL_WORLD_GROUND_TRUTH.get(fid, "")
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

                notes = "OK" if cer < 0.1 else f"CER={cer*100:.1f}%"
                metrics.append(
                    RealWorldDocxMetric(
                        fixture_id=fid,
                        category=category,
                        tables_count=len(d.tables),
                        headings_count=len(hdgs),
                        paragraphs_count=len(para_texts),
                        images_count=img_count,
                        cer=round(cer, 4),
                        wer=round(wer, 4),
                        peak_memory_kib=round(peak / 1024.0, 1),
                        duration_ms=round((t1 - t0) * 1000.0, 2),
                        visual_render_status=visual_status,
                        notes=notes,
                    )
                )
            except Exception as exc:
                metrics.append(
                    RealWorldDocxMetric(
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


def format_real_world_markdown_table(metrics: list[RealWorldQualityMetric]) -> str:
    lines = [
        "| Fixture | Category | Pages | Chars Extr. | CER | WER | Unicode | Reading Order | Peak Mem (KiB) | Time (ms) | Classification | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        uni = "PASS" if m.unicode_preserved else "FAIL"
        ro = "PASS" if m.reading_order_valid else "NON-LINEAR"
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.page_count} | {m.char_count_extracted} | {m.cer*100:.1f}% | {m.wer*100:.1f}% | {uni} | {ro} | {m.peak_memory_kib} | {m.duration_ms} | `{m.classification}` | {m.notes} |"
        )
    return "\n".join(lines)


def format_real_world_docx_markdown_table(metrics: list[RealWorldDocxMetric]) -> str:
    lines = [
        "| Fixture | Category | Tables | Headings | Paragraphs | Images | CER | WER | Visual QA | Mem (KiB) | Time (ms) | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.tables_count} | {m.headings_count} | {m.paragraphs_count} | {m.images_count} | {m.cer*100:.1f}% | {m.wer*100:.1f}% | {m.visual_render_status} | {m.peak_memory_kib} | {m.duration_ms} | {m.notes} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    rw_dir = _root / "tests" / "fixtures" / "real_world_documents"
    if not (rw_dir / "rw_01_technical_specification.pdf").exists():
        generate_real_world_fixtures(rw_dir)

    print("\n# LocalShift Real-World Document Benchmark Results (Native Mode)\n")
    native_metrics = evaluate_all_real_world_fixtures(rw_dir, ocr_mode="native_only")
    print(format_real_world_markdown_table(native_metrics))

    print("\n# LocalShift Real-World Document Benchmark Results (Auto OCR Mode)\n")
    auto_metrics = evaluate_all_real_world_fixtures(rw_dir, ocr_mode="auto")
    print(format_real_world_markdown_table(auto_metrics))

    print("\n# LocalShift Real-World PDF -> DOCX Reconstruction Results\n")
    docx_metrics = evaluate_real_world_docx_fixtures(rw_dir)
    print(format_real_world_docx_markdown_table(docx_metrics))
