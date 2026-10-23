# LocalShift — Project Status & Roadmap

**Current Version:** 0.6.0  
**Active Workstream:** Backend Document Engine & Offline OCR Foundation  
**Total Tests:** 333 collected (330 passing, 3 skipped, 0 failing)  

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
| **LS-BE-006C** | Quality verification, benchmark corpus & extraction reliability | Uncommitted | 311 passed | Complete |
| **LS-BE-006D** | Offline OCR engine foundation & scanned PDF extraction | Uncommitted | 330 passed | **Complete (Current)** |

---

## 2. Architecture Overview

- **Adapter Architecture:** `ConversionAdapter` protocol with `PillowImageAdapter` and `PdfDocumentAdapter`.
- **Capability Registry:** Thread-safe `AdapterRegistry` with explicit directional route mapping (21 routes).
- **Execution Boundary:** `convert_request()` enforcing:
  1. Input existence, regular file, symlink resolution, and 250 MiB size checks.
  2. Format resolution via magic-byte sniffing (`%PDF-` for documents, Pillow header for images).
  3. Output destination reservation and collision avoidance (` (2)`, ` (3)`).
  4. Atomic output replacement via temporary file.
  5. Correctness checks on output file size.
- **Document Engine & OCR:**
  - `PdfInspector`: Page counts, point dimensions, rotation angles, object counts, classification (`TEXT_PRESENT`, `IMAGE_LIKELY`, `MIXED_OR_UNCERTAIN`, `EMPTY_OR_UNKNOWN`, `UNREADABLE`), and reading order heuristics.
  - `PdfPageRenderer`: Memory-bounded page rendering via pypdfium2 with DPI clamping (72–400) and strict pixel ceiling (16 MP).
  - `RapidOcrEngine`: Offline CPU-first OCR using RapidOCR and ONNX Runtime with bundled PP-OCRv4 models (Apache-2.0).
  - `reconstruct_reading_order`: Deterministic 2D line-grouping and reading-order reconstruction.
  - `NativePdfTextExtractor`: Safe page-by-page extraction, per-page routing (`auto`, `native_only`, `force_ocr`), cooperative cancellation, and clean UTF-8 plain-text formatting.
  - `Quality Evaluator`: Automated CER, WER, latency, and heap memory tracing against 14 benchmark fixtures.

---

## 3. Next Milestone Recommendation

- **Milestone LS-BE-006E:** PDF → DOCX Document Structure & Reconstruction  
  - Implement structured reconstruction of paragraphs, headings, tables, and images into valid OpenXML Word documents (`.docx`).
  - Maintain privacy-first offline local processing.
