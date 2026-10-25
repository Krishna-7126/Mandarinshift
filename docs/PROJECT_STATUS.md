# LocalShift — Project Status & Roadmap

**Current Version:** 0.14.0 (Final Release)  
**Active Workstream:** Final Release & GitHub Publication Readiness (LS-BE-016)  
**Total Tests:** 566 collected (563 passing, 3 skipped, 0 failing)  

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
| **LS-BE-007C** | PDF → DOCX Unseen-Document Validation & Reliability Audit | `ee77f3a` | 366 passed | Complete |
| **LS-BE-007D** | OCR Quality Engineering, Language Support & Scanned PDF Reliability | `6a8097b` | 372 passed | Complete |
| **LS-BE-008A** | Real-World PDF → DOCX Reliability & Quality Validation | Working tree | 376 passed | Complete |
| **LS-BE-008B** | Independent Holdout Validation & Conversion Quality Gate | Working tree | 377 passed | Complete |
| **LS-BE-009** | DOCX → PDF Conversion Engine: Feasibility, Implementation & Verification | Working tree | 403 passed | Complete |
| **LS-BE-010** | PDF → PNG/JPEG Conversion Engine, Batch Export & Verification | Working tree | 442 passed | Complete |
| **LS-BE-011** | Image → PDF Conversion Engine, Multi-Image Assembly & Verification | Working tree | 481 passed | Complete |
| **LS-BE-012** | PDF Workbench Engine: Merge, Split, Reorder & Rotate | Working tree | 522 passed | Complete |
| **LS-BE-013** | Unified PySide6 GUI Integration & PDF Workbench UX | Working tree | 552 passed | Complete |
| **LS-BE-014** | Windows Packaging, Installer & Release Readiness | Working tree | 558 passed | Complete |
| **LS-BE-015** | Release Candidate QA, Installation Reliability & Stability Audit | Working tree | 563 passed | Complete |
| **LS-BE-016** | Final Release & GitHub Publication Readiness | Working tree | 563 passed | **Complete (Current)** |

---




## 2. Architecture Overview

- **Adapter Architecture:** `ConversionAdapter` protocol implemented by `PillowImageAdapter`, `PdfDocumentAdapter`, `DocxToPdfAdapter`, and `ImageToPdfAdapter`.
- **Capability Registry:** Thread-safe `AdapterRegistry` with dynamic backend availability checks across 30 registered conversion routes (or 29 without LibreOffice/Word COM). Routes requiring offline rendering backends (`docx -> pdf`) are advertised only when a functional backend (LibreOffice or Word COM) is detected.
- **Execution Boundary:** `convert_request()` enforcing:
  1. Input existence, regular file, symlink resolution, and 250 MiB size checks.
  2. Format resolution via magic-byte sniffing (`%PDF-` for documents, Pillow header for images, `PK\x03\x04` for DOCX).
  3. Output destination reservation and collision avoidance (` (1)`, ` (2)`).
  4. Atomic output replacement via temporary file.
  5. Correctness checks on output file size.
- **Document Engine, OCR & Workbench:**
  - `PdfInspector`: Page counts, point dimensions, rotation angles, object counts, classification (`TEXT_PRESENT`, `IMAGE_LIKELY`, `MIXED_OR_UNCERTAIN`, `EMPTY_OR_UNKNOWN`, `UNREADABLE`), and reading order heuristics.
  - `PdfPageRenderer`: Memory-bounded page rendering via pypdfium2 with DPI clamping (72–400), strict pixel ceiling (16 MP), and NumPy memory ownership (`.copy()`) ensuring zero Use-After-Free risks upon bitmap closure.
  - `RapidOcrEngine`: Offline CPU-first OCR using RapidOCR and ONNX Runtime with bundled PP-OCRv4 models (Apache-2.0), featuring automatic 180° upside-down scan inversion and 90°/270° sideways scan orientation recovery.
  - `reconstruct_reading_order`: Deterministic 2D line-grouping and reading-order reconstruction.
  - `NativePdfTextExtractor`: Safe page-by-page extraction, per-page routing (`auto`, `native_only`, `force_ocr`), cooperative cancellation, robust text de-duplication (`_is_duplicate_text`), and clean UTF-8 plain-text formatting.
  - `PdfToDocxReconstructor`: Structured document reconstruction pipeline into Microsoft Word (.docx) with multi-level headings (including `Article` and Roman numerals), conservative paragraph grouping (respecting semicolons and numbered list boundaries), native table detection (bordered, borderless, accounting negative formats e.g. `($1,250.00)`, and header-derived leading column alignment), table header bolding, numeric right-alignment, embedded raster image extraction placed above captions, and orientation preservation.
  - `DocxToPdfRenderer`: Offline document rendering subsystem translating Word documents to PDF via headless LibreOffice or Microsoft Word COM automation with sandboxed temp folder execution, source file read-only immutability, subprocess timeout monitoring, cooperative cancellation, and complete temporary file cleanup.
  - `PdfToImageExporter`: Resource-bounded rasterization subsystem exporting PDF pages to individual PNG or JPEG images with flexible page selection, configurable DPI and JPEG quality, custom naming tokens, atomic per-page placement, and collision safety.
  - `ImageToPdfConverter` & `ImageToPdfAdapter`: Robust offline conversion and assembly engine translating raster images (`png`, `jpeg`, `webp`, `bmp`, `tiff`) into compliant PDF documents with configurable page sizes (`original`, `a4`, `letter`), fitting geometries (`contain`, `cover`), orientation (`portrait`, `landscape`, `auto`), point margins, alpha background compositing, non-RGB conversions, EXIF auto-transposition, pixel ceilings, atomic output placement, and multi-image ordered multipage assembly.
  - `PdfWorkbench`: High-performance, fully offline structural manipulation engine supporting multi-PDF merging in explicit sequence, split to single-page PDFs or subsets, single-document page extraction, 1-based index reordering, and 90°/180°/270° page rotation with relative or absolute modes, input source immutability, and atomic placement.
  - `PySide6 Desktop GUI Subsystem` (`localshift.gui`): Modern, minimal, native Windows desktop application with 5 dedicated workflow tabs (`FileConverterTab`, `DocxInterchangeTab`, `PdfRasterizeTab`, `ImagesToPdfTab`, `PdfWorkbenchTab`), responsive `QThread` workers with cooperative cancellation, drag-and-drop file ingestion, dynamic route-aware option binding, real-time backend discovery badges, and complete isolation from backend core libraries (no PySide6 imports in backend modules).
  - `Windows Packaging & Installer Subsystem` (`packaging/`): Automated PyInstaller onedir packaging producing dual Windows executables (`LocalShift.exe` GUI and `localshift-cli.exe` console binary) with embedded PE version resources (v0.14.0.0), multi-resolution icons, bundled OCR ONNX models, `pdfium.dll`, `onnxruntime.dll`, OpenXML templates, and reproducible Inno Setup 6 installer (`LocalShift-Setup-0.14.0.exe`) with silent `/VERYSILENT` installation, per-user/all-users support, and clean uninstaller (`unins000.exe`).
  - `Quality Evaluators & Holdout Harness`: Comprehensive evaluation framework across 18 synthetic benchmark fixtures, 10 unseen validation fixtures, 10 real-world fixtures (`rw_01` to `rw_10`), 10 separate untouched holdout fixtures (`holdout_01` to `holdout_10`), and 6 DOCX-to-PDF fixtures (`docx_01` to `docx_06`).

---

## 3. Next Milestone Recommendation

- **Milestone LS-BE-015:** Office Document Text Extraction & Batch DOCX Ingestion
  - Implement native DOCX text, heading, table, and metadata extraction (`DocxInspector`, `DocxTextExtractor`).
  - Add `docx` → `txt` conversion route.
  - Optimize batch document queue scheduling and resource throttling.


