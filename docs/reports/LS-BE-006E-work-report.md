# LOCALSHIFT — WORK REPORT
# LS-BE-006E: Hybrid PDF Extraction Reliability, OCR Accuracy & Compatibility Audit

**Date:** 2026-10-23  
**Status:** COMPLETE  
**Author:** Senior Backend Engineer & PDF/OCR Reliability Specialist  
**Environment:** Python 3.14.3 (AMD64), Windows 11, ONNX Runtime CPU v1.26.0  

---

## 1. Executive Summary

Milestone **LS-BE-006E** completes a rigorous reliability, accuracy, and compatibility audit of LocalShift's hybrid PDF text extraction and offline OCR pipeline.

Key findings and deliverables:
1. **Root-Cause Analysis of 6.4% CER:** Investigated the English scanned invoice benchmark (`doc_05_english_scan.pdf`). Traced character discrepancies to: (a) absence of inter-word whitespace tokens in PP-OCR CTC decoding for fused bounding boxes (`SCANNEDINVOICE`), (b) low-contrast font confusion between colons and periods (`:` vs `.`), and (c) digit `0` vs letter `o` confusion (`$0.00` vs `$o.0o`). Confirmed these reflect intrinsic model behavior on bitmap-rendered text rather than code regression.
2. **Buffer Memory Ownership & Security Hardening:** Discovered that `pypdfium2.PdfBitmap.to_numpy()` returned an unowned view into the C++ bitmap memory. When `bmp.close()` executed, the NumPy array pointed to deallocated memory. Hardened `PdfPageRenderer.render_page()` with an explicit `.copy()` call, ensuring NumPy memory ownership (`OWNDATA: True`) and eliminating Use-After-Free hazards.
3. **Robust Text De-duplication:** Identified that combining native text and OCR text on mixed or forced-OCR pages produced duplicate text lines when whitespace or punctuation varied. Implemented normalized token overlap de-duplication (`_is_duplicate_text`), preventing duplicated paragraphs and ensuring `force_ocr` cleanly outputs only OCR results.
4. **OCR Model & Language Audit:** Conducted an empirical audit of the bundled model (`ch_PP-OCRv3_rec_infer.onnx`, 10.7 MB, SHA256: `897a3ededb38fee0...`). Verified that its dictionary contains 6,624 character classes covering Latin and Chinese, but **zero Devanagari characters**. Confirmed that Hindi scanned text cannot be extracted by the default model without downloading specialized weights, preserving our strict offline-first, no-silent-download policy.
5. **Awesome-Copilot Review:** Audited `.github/instructions/code-review-generic.instructions.md`. Confirmed it provides clean, non-intrusive code review guidelines focused on security, data safety, and conversion boundaries. Contains no executable hooks or telemetry; retained as safe documentation.
6. **Full Verification:** Test suite expanded from 330 to **335 passing tests** (3 skipped on non-admin Windows symlinks, 0 failed). Benchmark harness updated to report both native and auto OCR modes.

---

## 2. Initial Audit

### A. Current Architecture & Extraction Flow
- **Execution Pipeline:** `convert_request()` (`converter.py`) -> `PdfDocumentAdapter` (`adapter.py`) -> `NativePdfTextExtractor.extract()` (`text_extractor.py`).
- **Page Inspection:** `PdfInspector` analyzes page objects without rasterization to classify pages into `TEXT_PRESENT`, `IMAGE_LIKELY`, `MIXED_OR_UNCERTAIN`, `EMPTY_OR_UNKNOWN`, or `UNREADABLE`.
- **Hybrid Routing:**
  - `TEXT_PRESENT`: Fast native stream extraction via PDFium (sub-millisecond latency).
  - `IMAGE_LIKELY`: Memory-bounded rasterization at 200 DPI (`PdfPageRenderer`) followed by CPU OCR (`RapidOcrEngine`).
  - `EMPTY_OR_UNKNOWN`: Emits empty string without running OCR (guarantees zero hallucinated text).
  - `MIXED_OR_UNCERTAIN`: Native extraction with OCR fallback for sparse pages.
- **Reading Order:** `reconstruct_reading_order()` groups detector boxes with ≥ 45% vertical overlap, sorting left-to-right within lines and top-to-bottom across lines.

### B. Awesome-Copilot Files
- **File:** `.github/instructions/code-review-generic.instructions.md`
- **Source:** Adapted from GitHub Awesome-Copilot generic code review instructions.
- **Relevance & Safety:** Provides developer guidance for code reviews. Mentions LocalShift conversion boundaries, security invariants, and offline guarantees. Zero scripts, hooks, or network calls.

### C. Test & Benchmark Baseline
- 330 tests passing, 3 skipped.
- 14-fixture synthetic benchmark corpus (`doc_01` to `doc_14`).

### D. Identified Defects & Vulnerabilities
1. **Use-After-Free Memory Risk:** `renderer.py` returned an unowned NumPy array view (`OWNDATA: False`) while closing the underlying C++ bitmap.
2. **Text Duplication:** `text_extractor.py` appended OCR text to native text if formatting differed slightly, causing duplicated lines on `force_ocr` and mixed pages.
3. **Defense-in-depth size check:** `PdfDocumentAdapter` did not independently verify `context.max_input_bytes`.
4. **Uncalibrated Rotated Benchmark Metrics:** 77.4% CER on `doc_08_rotated_page.pdf` was caused by visual rotated coordinate line reversal vs stream generation order, not character errors.

---

## 3. Changes and Technical Rationale

| File | Change | Technical Rationale |
|---|---|---|
| `src/localshift/documents/renderer.py` | `img_arr = bmp.to_numpy().copy()` | Enforces NumPy data ownership (`OWNDATA: True`) before `bmp.close()` executes in `finally`, eliminating dangling pointer risks. |
| `src/localshift/documents/text_extractor.py` | Added `_is_duplicate_text()` and updated merge logic | Normalizes whitespace and computes token overlap (≥ 75%) to detect whether native text is already represented in OCR text. In `force_ocr`, ignores pre-existing native text. |
| `src/localshift/documents/adapter.py` | Added `context.max_input_bytes` check | Defense-in-depth size limit enforcement before document opening. |
| `tests/pdf_quality_evaluator.py` | Support `ocr_mode` in `evaluate_all_fixtures()` | Enables benchmark reporting in both pure native mode and auto OCR mode. |
| `tests/test_pdf_ocr.py` | Added 5 tests in `TestPdfOcrReliabilityHardening` | Covers buffer memory ownership, `force_ocr` de-duplication, `_is_duplicate_text` unit tests, `max_input_bytes`, and language model dictionary audit. |

---

## 4. Files Added and Modified

### Modified Files:
1. `src/localshift/documents/renderer.py`
2. `src/localshift/documents/text_extractor.py`
3. `src/localshift/documents/adapter.py`
4. `tests/pdf_quality_evaluator.py`
5. `tests/test_pdf_ocr.py`
6. `docs/PROJECT_STATUS.md`
7. `docs/TEST_PLAN.md`
8. `TASKS.md`

### Created Files:
1. `docs/reports/LS-BE-006E-work-report.md` (this report)

---

## 5. Benchmark Methodology and Results

Benchmarks evaluated using `tests/pdf_quality_evaluator.py` on the 14-fixture corpus.

### Benchmark Results (Native Mode vs. Auto OCR Mode)

| Fixture | Category | Native Chars | Native CER | Auto OCR Chars | Auto OCR CER | Auto OCR WER | OCR Applied | Notes |
|---|---|---|---|---|---|---|---|---|
| `doc_01_simple_digital` | Simple digital | 157 | 0.0% | 157 | 0.0% | 0.0% | No | Native exact match |
| `doc_02_multipage_digital` | Multipage digital | 246 | 0.0% | 246 | 0.0% | 0.0% | No | 3 pages sequential flow |
| `doc_03_multicolumn` | Multi-column | 162 | 0.0% | 162 | 0.0% | 0.0% | No | Sequential column flow |
| `doc_04_table` | Tables | 201 | 0.0% | 201 | 0.0% | 0.0% | No | Native table stream |
| `doc_05_english_scan` | English raster scan | 0 | 100.0% | **124** | **5.5%** | **46.7%** | **Yes** | **All 4 lines recognized** |
| `doc_06_hindi_scan` | Hindi raster scan | 0 | 100.0% | 56 | 46.5% | 50.0% | Yes | English header recognized; Devanagari missing |
| `doc_07_mixed_pages` | Mixed pages | 82 | 0.0% | **206** | **3.3%** | **28.0%** | **Page 2** | **Page 1 native, Page 2 OCR** |
| `doc_08_rotated_page` | Rotated page (90°) | 62 | 77.4% | 62 | 77.4% | 66.7% | No | Rotated visual line order |
| `doc_09_corrupt` | Damaged PDF | 0 | N/A | 0 | N/A | N/A | No | Safe error trapping |
| `doc_10_encrypted` | Password protected | 0 | N/A | 0 | N/A | N/A | No | Password warning |
| `doc_11_unicode_digital` | Multilingual Unicode | 216 | 0.0% | 216 | 0.0% | 0.0% | No | Accents & currency symbols |
| `doc_12_hierarchy` | Structural hierarchy | 300 | 0.0% | 300 | 0.0% | 0.0% | No | Headings & paragraphs |
| `doc_13_empty` | Blank page | 0 | 0.0% | **0** | **0.0%** | **0.0%** | **Bypass** | **0 chars, 0 hallucination** |
| `doc_14_interleaved_multicolumn` | Interleaved columns | 51 | 7.8% | 51 | 7.8% | 25.0% | No | Stream-order diagnostic |

---

## 6. Test Commands and Actual Results

### Focused Test Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 -m pytest tests/test_pdf_ocr.py
```
**Result:** 24 passed in 8.18s.

### Full Regression Suite Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 -m pytest
```
**Result:** 335 passed, 3 skipped in 12.12s.

### Benchmark Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 tests/pdf_quality_evaluator.py
```
**Result:** Zero errors; generated complete comparison markdown tables for Native and Auto OCR modes.

---

## 7. Accuracy, Language and Compatibility Limitations

1. **English Scan Accuracy:** 5.5% normalized CER (6.4% raw CER) is achieved on `doc_05_english_scan.pdf`. The error is localized to collapsed whitespace in single boxes (`SCANNEDINVOICE`) and colon vs. period substitutions.
2. **Hindi / Devanagari Limitation:** The bundled ONNX model contains 6,624 character classes covering Latin, punctuation, and Chinese glyphs. It contains **0 Devanagari tokens**. Hindi text cannot be recognized without an auxiliary language model.
3. **Rotated Page Reading Order:** For native extraction on rotated pages, PDFium extracts glyphs according to content stream order or visual rotation, which can invert line order relative to unrotated coordinate creation.
4. **Multi-Column Scans:** Complex multi-column scans (e.g. dense newspapers) require layout-analysis networks (like PP-Structure) to reliably split columns before reading-order sorting.

---

## 8. Security and Licensing Findings

1. **Memory Safety:** Bounded rasterization protects against ZIP-bomb/decompression memory exhaustion (`MAX_IMAGE_PIXELS = 16_000_000`). Explicit `.copy()` prevents Use-After-Free vulnerabilities.
2. **Untrusted Input:** File size (250 MiB) and page limits (2000 pages) prevent resource exhaustion. Password-protected and corrupted files fail safely without crashing.
3. **Licensing:**
   - `rapidocr-onnxruntime`: Apache-2.0.
   - Bundled PP-OCRv4 weights: Apache-2.0.
   - `onnxruntime`: MIT.
   - `pypdfium2`: Apache-2.0 / BSD-3.
   - Zero GPL / AGPL contamination.

---

## 9. Awesome-Copilot Review Decisions

- **File Evaluated:** `.github/instructions/code-review-generic.instructions.md`.
- **Decision:** **ACCEPTED & PRESERVED**.
- **Rationale:** The document defines useful guidelines for code reviews (focusing on security, data safety, regressions, and conversion invariants). It contains no scripts, hooks, or telemetry. It respects LocalShift's core conventions.

---

## 10. Remaining Risks and Recommended Next Milestone

- **Remaining Risk:** Dense multi-column scanned documents or complex tables with borderless cells can interleave columns during reading-order reconstruction.
- **Recommended Next Milestone:** **LS-BE-006F: PDF → DOCX Document Structure & Layout Reconstruction**.
  - Reconstruct paragraphs, headings, table structures, and embedded images into valid OpenXML Word documents (`.docx`).

---

## 11. Git Status

- **Branch:** `main`
- **Head Commit:** `3100a1f`
- **Working Tree:** Clean modifications ready for review.
- **No changes discarded, reset, or pushed.**

---

**Final Milestone Status:** COMPLETE
