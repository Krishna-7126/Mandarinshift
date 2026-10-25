# LocalShift — Project Status & Roadmap

**Current Version:** 0.7.2  
**Active Workstream:** PDF → DOCX Unseen-Document Validation & Reliability Audit (LS-BE-007C)  
**Total Tests:** 369 collected (366 passing, 3 skipped, 0 failing)  

---

## 1. Milestone Progress

| Milestone | Scope | Commit / State | Tests Passing | Status |
|---|---|---|---|---|
| **LS-BE-001** | Core Pillow image conversion engine | Initial baseline | 62 passed | Complete |
| **LS-BE-002** | Asynchronous JobQueue & batch execution | `2b38dc3` | 142 passed | Complete |
| **LS-BE-003** | Concurrency safety, collision prevention & atomicity | `6fc81e8` | 193 passed | Complete |
| **LS-BE-004** | Adapter architecture, registry & error taxonomy | `be92f01` | 224 passed | Complete |
| **LS-BE-005** | Conversion planning & preflight validation API | `17a93f4` | 254 passed | Complete |
| **LS-BE-006A** | Document engine foundation & dependency verification | `17a93f4` | 259 passed | Complete |
| **LS-BE-006B** | PDF inspection & native text extraction adapter | `30d3da4` | 291 passed | Complete |
| **LS-BE-006C** | Quality verification, benchmark corpus & extraction reliability | `3100a1f` | 311 passed | Complete |
| **LS-BE-006D** | Offline OCR engine foundation & scanned PDF extraction | `3100a1f` | 330 passed | Complete |
| **LS-BE-006E** | Hybrid PDF reliability, OCR accuracy & compatibility audit | `ee77f3a` | 335 passed | Complete |
| **LS-BE-007A** | PDF → DOCX Conversion Engine: Architecture, Implementation & Verification | `ee77f3a` | 354 passed | Complete |
| **LS-BE-007B** | PDF → DOCX Quality Verification, Visual Fidelity & Real-World Benchmarking | `ee77f3a` | 359 passed | Complete |
| **LS-BE-007C** | PDF → DOCX Unseen-Document Validation & Reliability Audit | Working tree | 366 passed | **Complete (Current)** |

---

## 2. Architecture Overview

- **Adapter Architecture:** `ConversionAdapter` protocol with `PillowImageAdapter` and `PdfDocumentAdapter`.
- **Capability Registry:** Thread-safe `AdapterRegistry` with explicit directional route mapping (22 routes).
- **Execution Boundary:** `convert_request()` enforcing:
  1. Input existence, regular file, symlink resolution, and 250 MiB size checks.
  2. Format resolution via magic-byte sniffing (`%PDF-` for documents, Pillow header for images, `PK\x03\x04` for DOCX).
  3. Output destination reservation and collision avoidance (` (1)`, ` (2)`).
  4. Atomic output replacement via temporary file.
  5. Correctness checks on output file size.
- **Document Engine & OCR:**
  - `PdfInspector`: Page counts, point dimensions, rotation angles, object counts, classification (`TEXT_PRESENT`, `IMAGE_LIKELY`, `MIXED_OR_UNCERTAIN`, `EMPTY_OR_UNKNOWN`, `UNREADABLE`), and reading order heuristics.
  - `PdfPageRenderer`: Memory-bounded page rendering via pypdfium2 with DPI clamping (72–400), strict pixel ceiling (16 MP), and NumPy memory ownership (`.copy()`) ensuring zero Use-After-Free risks upon bitmap closure.
  - `RapidOcrEngine`: Offline CPU-first OCR using RapidOCR and ONNX Runtime with bundled PP-OCRv4 models (Apache-2.0).
  - `reconstruct_reading_order`: Deterministic 2D line-grouping and reading-order reconstruction.
  - `NativePdfTextExtractor`: Safe page-by-page extraction, per-page routing (`auto`, `native_only`, `force_ocr`), cooperative cancellation, robust text de-duplication (`_is_duplicate_text`), and clean UTF-8 plain-text formatting.
  - `PdfToDocxReconstructor`: Structured document reconstruction pipeline into Microsoft Word (.docx) with multi-level headings, conservative paragraph grouping, native table detection (bordered and borderless), table header bolding, numeric right-alignment, embedded raster image extraction placed above captions, and orientation preservation.
  - `Quality Evaluator`: Automated CER, WER, latency, and heap memory tracing against 18 benchmark fixtures in native mode, auto OCR mode, and DOCX reconstruction mode with offline visual QA rendering via Microsoft Word COM automation.

---

## 3. Next Milestone Recommendation

- **Milestone LS-BE-008:** Document Conversion Route Expansion & Office Ingestion Foundation
  - Implement DOCX inspection and text extraction engine.
  - Establish DOCX → PDF route design using available local rendering engines.
  - Add bidirectional document format tests and preflight capability discovery.
