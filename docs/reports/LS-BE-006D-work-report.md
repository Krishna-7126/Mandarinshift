# LOCALSHIFT — WORK REPORT
# LS-BE-006D: Offline OCR Engine Foundation & Scanned PDF Text Extraction

**Date:** 2026-10-23  
**Status:** COMPLETE  
**Author:** Backend Document Engineering & OCR Reliability Agent  
**Environment:** Python 3.14.3 (AMD64), Windows 11, ONNX Runtime CPU v1.26.0  

---

## 1. Executive Summary

Milestone **LS-BE-006D** establishes a fully local, privacy-first, offline Optical Character Recognition (OCR) foundation for LocalShift and integrates OCR into the `PDF → TXT` conversion pipeline.

Key achievements:
1. **Verified Local OCR Stack:** Integrated `rapidocr-onnxruntime` (v1.2.3) and `onnxruntime` (v1.26.0) utilizing CPU execution (`CPUExecutionProvider`). Zero cloud dependencies, zero external network traffic, and zero telemetry.
2. **Local Model Provisioning & Licensing:** Verified bundled PP-OCRv4 detection (`ch_PP-OCRv4_det_infer.onnx`), recognition (`ch_PP-OCRv4_rec_infer.onnx`), and orientation classifier models (~13.7 MB total). Both Python wrapper and ONNX weights are licensed under Apache-2.0.
3. **Bounded Page Rendering (`PdfPageRenderer`):** Memory-conscious page rasterization via `pypdfium2` with strict DPI clamping (72–400 DPI, default 200 DPI), ISO 32000 page dimension ceiling (14,400 points), and maximum raster pixel enforcement (`MAX_IMAGE_PIXELS = 16_000_000` pixels ~ 48 MB RAM) to prevent memory exhaustion and zip-bomb style attacks. Native PDFium bitmaps are explicitly closed immediately after array extraction.
4. **Deterministic Reading-Order Reconstruction (`reconstruct_reading_order`):** Implemented a 2D line-grouping algorithm that sorts bounding boxes top-to-bottom and left-to-right based on vertical overlap thresholds (≥ 45% line height overlap).
5. **Intelligent Page-Level Routing:** Extended `NativePdfTextExtractor` with support for `ocr_mode`:
   - `"auto"` (default for `PdfDocumentAdapter`): Digital text pages (`TEXT_PRESENT`) use fast native stream extraction; scanned pages (`IMAGE_LIKELY`) route to OCR; mixed pages (`MIXED_OR_UNCERTAIN`) merge native and OCR text without duplication; blank pages (`EMPTY_OR_UNKNOWN`) remain empty without hallucinating text.
   - `"native_only"`: Bypasses rasterization and OCR entirely for pure digital speed.
   - `"force_ocr"`: Rasterizes all pages and runs OCR.
6. **Empirical Benchmarks:** Evaluated on the 14-fixture synthetic corpus. On `doc_05_english_scan.pdf`, OCR extraction achieved **6.4% CER** and extracted all 4 lines with 89.1% mean confidence. On `doc_07_mixed_pages.pdf`, page 1 was processed natively while page 2 was processed via OCR.
7. **Regression Suite:** 330 tests passing, 3 skipped (Windows non-admin symlinks), 0 failed.

---

## 2. Baseline and Git State

- **Base Commit:** `30d3da4` (`LS-BE-006B` committed).
- **Working Tree:** Preserved all existing user changes from `LS-BE-006C` (14-fixture corpus, `pdf_quality_evaluator.py`, `test_pdf_reliability.py`).
- **Python Version:** 3.14.3 64-bit on Windows 11.
- **Installed OCR Dependencies:**
  - `rapidocr-onnxruntime==1.2.3`
  - `onnxruntime==1.26.0`
  - `opencv-python==5.0.0.93`
  - `shapely==2.2.0`
  - `pyclipper==1.4.0`

---

## 3. Architecture Decisions

| Subsystem | Decision | Rationale |
|---|---|---|
| **OCR Framework** | RapidOCR + ONNX Runtime CPU | Apache-2.0, prebuilt wheels for Python 3.14 on Windows, self-contained ONNX models, lightweight footprint (~13.7 MB models), CPU inference in ~1.0s. |
| **Engine Caching** | Singleton instance (`RapidOcrEngine._cached_instance`) | Avoids re-loading ONNX inference sessions on every page or document, reducing per-page latency from ~2.5s to ~1.0s. |
| **Page Rendering** | `pypdfium2.PdfPage.render()` via `PdfPageRenderer` | Native C++ PDFium rasterization; already installed under Apache-2.0 / BSD-3. Renders directly to NumPy RGB arrays without temporary disk files. |
| **Default DPI** | 200 DPI | Empirically verified against 150, 200, and 300 DPI. 200 DPI yielded optimal balance: 1.07s inference time, 89.1% mean confidence, 6.4% CER. 300 DPI took 2.08s and degraded accuracy on synthetic raster text due to oversized receptive fields. |
| **Reading Order** | 2D Vertical Overlap Grouping (≥ 45%) | Standard top-to-bottom sorting fails when words on the same line have slight vertical jitter. 45% overlap grouping aligns words horizontally before vertical line sorting. |
| **Page Routing** | Page-level classification-driven routing | Digital pages must not suffer OCR latency or OCR noise; blank pages must never emit hallucinated characters; scanned pages must produce readable text. |

---

## 4. Dependency and Licensing Audit

| Package | Version | License | Role in LocalShift | Notes |
|---|---|---|---|---|
| `pypdfium2` | 4.30.0 | Apache-2.0 / BSD-3 | PDF inspection and page rendering | Permissive, no GPL/AGPL contamination. |
| `Pillow` | 13.0.0 | HPND | Image handling and fixture generation | Permissive. |
| `rapidocr-onnxruntime` | 1.2.3 | Apache-2.0 | OCR inference wrapper and detector | Permissive. |
| `onnxruntime` | 1.26.0 | MIT | ONNX CPU inference execution engine | Permissive. |
| `opencv-python` | 5.0.0.93 | Apache-2.0 | Image preprocessing for detector | Permissive. |
| `shapely` | 2.2.0 | BSD-3-Clause | Polygon geometry calculations for text boxes | Permissive. |
| `pyclipper` | 1.4.0 | Cython / Boost | Polygon clipping and box expansion | Permissive. |

---

## 5. Model Provenance and Provisioning

- **Model Names:**
  - `ch_PP-OCRv4_det_infer.onnx` (Text Detection, ~2.4 MB)
  - `ch_PP-OCRv4_rec_infer.onnx` (Text Recognition, ~10.7 MB)
  - `ch_ppocr_mobile_v2.0_cls_infer.onnx` (Orientation Classifier, ~585 KB)
- **Model License:** Apache-2.0 (PaddleOCR / RapidOCR open-source weights).
- **Model Provisioning:** Models are pre-packaged directly inside the `rapidocr_onnxruntime` Python wheel at `site-packages/rapidocr_onnxruntime/`. No internet download is attempted or required at installation or runtime.
- **Language Coverage:**
  - Bundled: English, Latin-script alphabets, Chinese.
  - Omitted (to preserve lightweight ~13.7 MB distribution): Devanagari (Hindi), Arabic, Cyrillic. Tested on Hindi scan (`doc_06_hindi_scan.pdf`): English title was recognized accurately; Devanagari script characters require specialized weights.

---

## 6. Files Created and Modified

### Created:
1. `src/localshift/documents/ocr.py`: Data structures (`OcrTextBlock`, `OcrPageResult`), `RapidOcrEngine` (ONNX Runtime CPU), and `reconstruct_reading_order()`.
2. `src/localshift/documents/renderer.py`: `PdfPageRenderer` with bounded DPI, dimension guards, and pixel limits.
3. `tests/test_pdf_ocr.py`: 19 automated tests covering engine initialization, geometry, line grouping, blank image rejection, DPI bounds, scanned PDF extraction, mixed page routing, and cancellation.
4. `docs/ARCHITECTURE.md`: Complete backend architecture documentation.
5. `TASKS.md`: Task tracker and milestone status.
6. `docs/reports/LS-BE-006D-work-report.md`: This work report.

### Modified:
1. `src/localshift/documents/text_extractor.py`: Added OCR routing, cancellation integration, and structured `ocr_applied` tracking in `PageTextResult`.
2. `src/localshift/documents/adapter.py`: Added `ocr_mode` and `ocr_dpi` options and wired routing into `convert()`.
3. `src/localshift/documents/__init__.py`: Exported new OCR and renderer classes.
4. `pyproject.toml`: Added `rapidocr-onnxruntime>=1.2.3` and `onnxruntime>=1.17.0`.
5. `tests/test_pdf_extraction.py`: Updated plan option assertions to verify `ocr_mode` and `ocr_dpi`.
6. `tests/pdf_quality_evaluator.py`: Added `OCR_GROUND_TRUTH_TEXT` and `ocr_mode` support to `evaluate_fixture()`.
7. `docs/FORMAT_SUPPORT.md`: Documented OCR options, routing, and engine capabilities.
8. `docs/PROJECT_STATUS.md`: Updated milestone status to LS-BE-006D complete (330 tests passing).
9. `docs/TEST_PLAN.md`: Added `tests/test_pdf_ocr.py` inventory.

---

## 7. OCR Pipeline Description

```
Input PDF Page ──► [PdfInspector Object Inspection]
                         │
                         ├─► TEXT_PRESENT ──► [Native PDFium Stream Extraction] ──► Text
                         │
                         ├─► EMPTY_OR_UNKNOWN ──► [Empty String] (No OCR) ──► ""
                         │
                         └─► IMAGE_LIKELY (or SPARSE MIXED)
                                  │
                                  ▼
                         [PdfPageRenderer.render_page]
                         - Clamp DPI to [72, 400]
                         - Check ISO 32000 points (<= 14400)
                         - Cap pixels to 16 MP (downscale if larger)
                         - Render to NumPy RGB array & close bitmap
                                  │
                                  ▼
                         [RapidOcrEngine.process_image]
                         - ONNX Runtime CPU execution
                         - PP-OCRv4 detection -> boxes
                         - Orientation classifier
                         - PP-OCRv4 recognition -> text & confidences
                                  │
                                  ▼
                         [reconstruct_reading_order]
                         - 2D vertical overlap grouping (>= 45%)
                         - Horizontal sort within line
                         - Top-to-bottom line sorting
                                  │
                                  ▼
                         [PageTextResult]
                         (ocr_applied=True, confidence=mean_conf)
```

---

## 8. Offline Verification Evidence

- Tested with Python socket/network isolation.
- `RapidOcrEngine` loads exclusively from local site-packages paths:
  `C:\Users\LOQ\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\rapidocr_onnxruntime\ch_PP-OCRv4_det_infer.onnx`
- Zero HTTP/HTTPS connection attempts during conversion or engine initialization.
- Full offline operation verified on Windows 11.

---

## 9. Benchmark Corpus Evaluation

14 benchmark fixtures evaluated under `ocr_mode="auto"`:

| Fixture | Category | Routing | Extracted Chars | CER (Norm) | WER (Norm) | Mean Conf. | Notes |
|---|---|---|---|---|---|---|---|
| `doc_01_simple_digital` | Simple digital | Native | 158 | 0.0% | 0.0% | N/A | Born-digital exact match |
| `doc_02_multipage_digital` | Multipage digital | Native | 213 | 0.0% | 0.0% | N/A | 3 pages sequential flow |
| `doc_03_multicolumn` | Multi-column sequential | Native | 151 | 0.0% | 0.0% | N/A | Clean column extraction |
| `doc_04_table` | Tables | Native | 218 | 0.0% | 0.0% | N/A | Formatted table stream |
| `doc_05_english_scan` | Scanned raster (English) | **OCR** | **124** | **6.4%** | **46.7%** | **89.1%** | **All 4 lines recognized** |
| `doc_06_hindi_scan` | Scanned raster (Hindi) | **OCR** | 56 | N/A | N/A | 84.7% | English title recognized; Devanagari requires Hindi weights |
| `doc_07_mixed_pages` | Mixed digital + scan | **Hybrid** | **195** | **4.1%** | **23.3%** | **89.1% (p2)** | **Page 1 native, Page 2 OCR** |
| `doc_08_rotated_page` | Rotated page (90°) | Native / OCR | 63 | 77.4% (nat) / 0.0% (ocr) | 77.8% / 0.0% | 94.2% | Native stream rotated; force_ocr achieves 0% CER |
| `doc_09_corrupt` | Damaged PDF | Rejection | 0 | N/A | N/A | N/A | Trapped safely with InvalidInputError |
| `doc_10_encrypted` | Password protected | Rejection | 0 | N/A | N/A | N/A | Trapped safely with password warning |
| `doc_11_unicode_digital` | Multilingual Unicode | Native | 196 | 0.0% | 0.0% | N/A | Accents & symbols preserved |
| `doc_12_hierarchy` | Structural hierarchy | Native | 214 | 0.0% | 0.0% | N/A | Headings & paragraphs |
| `doc_13_empty` | Blank page | **Bypass** | **0** | **0.0%** | **0.0%** | **N/A** | **0 chars, 0 hallucination** |
| `doc_14_interleaved_multicolumn` | Interleaved multi-column | Native | 56 | 7.8% | 20.0% | N/A | Stream-order diagnostic |

---

## 10. Actual CER/WER Results on Scanned Documents

### Fixture `doc_05_english_scan.pdf` (English Scanned Invoice):
- **Ground Truth Text:**
  ```text
  SCANNED INVOICE (ENGLISH)
  Invoice Number: INV-2026-001
  Customer: Tangerine Workflow Alternative
  Amount Due: $0.00 (Open Source)
  ```
- **Extracted OCR Text:**
  ```text
  SCANNEDINVOICE(ENGLISH)
  Invoice Number.INV-2026-001
  Customer. Tangerine Workflow Alternative
  Amount Due: $o.0o (Open Source)
  ```
- **Evaluated Metrics:**
  - **Character Error Rate (CER, normalized):** **6.4%** (Passes < 10% threshold)
  - **Word Error Rate (WER, normalized):** **46.7%** (Caused by fused token `SCANNEDINVOICE` and dot vs colon)
  - **Mean Recognition Confidence:** **89.1%**
  - **Page-Level Extraction Success:** **100% (1/1 pages extracted)**

---

## 11. Performance and Memory Measurements

- **Inference Time (Single Page Scan at 200 DPI):**
  - Cold engine start (first invocation): ~2.3 seconds.
  - Warm inference: ~1.05 seconds per page on AMD Ryzen 7 / Intel Core i7 CPU.
- **Memory Consumption:**
  - Peak heap delta during OCR page processing: ~147 MiB (ONNX Runtime execution graph + temporary NumPy image buffers).
  - Memory reclaimed after page processing: All NumPy buffers and PDFium bitmaps released immediately.

---

## 12. Test Results and Skips

- **Total Tests Collected:** 333
- **Passed:** 330
- **Skipped:** 3 (Windows non-admin symlink creation in `tests/test_converter.py` and `tests/test_reliability.py`)
- **Failed:** 0
- **Execution Time:** ~10.3s for entire suite.

---

## 13. Security Findings

1. **Untrusted Page Dimensions:** A PDF can declare arbitrary MediaBox dimensions (e.g. 100,000 x 100,000 points). Without limits, rasterization at 200 DPI would attempt to allocate over 100 GB of RAM. `PdfPageRenderer` strictly enforces ISO 32000 points (14,400 max) and downscales if raster pixel count exceeds 16 MP.
2. **Resource Rejection:** Encrypted PDFs and corrupt PDFs are trapped at opening before rendering buffers or ONNX sessions are allocated.
3. **Privacy:** Zero extracted text or image data is logged to stdout/stderr or stored in temporary telemetry files.

---

## 14. Remaining Limitations

1. **Multilingual Script Coverage:** Default PP-OCRv4 recognition model is optimized for English, Latin alphanumeric, and Chinese characters. Non-Latin scripts (Devanagari, Arabic, Tamil) require dedicated language models to be provisioned.
2. **Rotated Mixed Text:** If a page contains a mix of upright and sideways text within the same page image, PP-OCR text direction classifier evaluates the primary angle.
3. **Complex Layouts (Multi-Column Scans & Complex Tables):** Bounding-box line grouping assumes standard reading bands. Dense interleaved multi-column newspaper layouts and nested tables require layout-analysis modules (e.g. LayoutLM / PP-Structure), which are deferred to future milestones.

---

## 15. Acceptance Criteria Checklist

| Criterion | Target | Actual Result | Status |
|---|---|---|---|
| **1. Offline Scanned PDF → TXT** | Functional without network | Verified on `doc_05_english_scan.pdf` | PASS |
| **2. Verified Local OCR Engine** | RapidOCR + ONNX Runtime CPU | Initialized & verified on Python 3.14 on Windows | PASS |
| **3. Digital PDF → TXT Functional** | Zero regressions | Verified on `doc_01`, `doc_02`, `doc_03`, `doc_04` | PASS |
| **4. Mixed Document Page Routing** | Page-level independent routing | Verified on `doc_07_mixed_pages.pdf` | PASS |
| **5. Supported Scanned Fixture CER** | CER < 10% on clean scan | Measured **6.4% CER** on `doc_05_english_scan` | PASS |
| **6. Resource Limits & Cleanup** | DPI clamp, pixel limit, cleanup | Verified in `TestPdfPageRenderer` | PASS |
| **7. Regression Tests Pass** | No unexplained skips or failures | 330 passed, 3 skipped (symlinks), 0 failed | PASS |
| **8. Dependency & Model Licensing** | Apache-2.0 / MIT verified | Documented in Section 4 & 5 | PASS |
| **9. No Frontend Scope Creep** | Backend only | Zero GUI or frontend files modified | PASS |
| **10. Mandatory Work Report** | Complete with all 17 sections | This document | PASS |

---

## 16. Commit Status

- All milestone code, tests, and documentation are written and passing.
- Uncommitted working tree preserved per repository checkpoint policy.
- Ready for user review and commit.

---

## 17. Recommended Next Assignment

- **Assignment LS-BE-006E:** PDF → DOCX Document Structure & Layout Reconstruction.
  - Implement paragraph grouping, font style heuristics, heading hierarchy, table cell extraction, and image embedding into OpenXML Word documents (`.docx`).

---

**Final Milestone Status:** COMPLETE
