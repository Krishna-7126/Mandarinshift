# LocalShift — Work Report: Milestone LS-BE-010
## PDF → PNG/JPEG Conversion Engine, Batch Export & Verification

**Date:** 2026-10-25  
**Role:** Senior Backend Engineer, Conversion Architect, and QA Engineer  
**Status:** Completed & Verified  

---

### 1. Executive Summary

Milestone **LS-BE-010** delivers a reliable, fully offline **PDF → PNG** and **PDF → JPEG** conversion engine for LocalShift, completing the document rasterization export capabilities.

Key achievements:
1. **Registered Conversion Routes:** Added `pdf` → `png` and `pdf` → `jpeg` directional conversion routes across `PdfDocumentAdapter`, `AdapterRegistry`, `ConversionPlanner`, and `formats.py`, expanding the total registered routes to 25.
2. **Offline-First & Resource-Bounded:** Uses existing local rendering architecture (`PdfPageRenderer` via Google PDFium and Pillow). 100% offline, zero network telemetry, zero third-party cloud services. Enforces strict DPI limits (72–400) and maximum pixel memory ceilings (16 MP per page).
3. **Multipage Batch Export & Page Selection:** Supports full document export or granular page selection via `parse_page_selection()` (`"all"`, single page `2`, ranges `"1-3"`, comma lists `"1, 3, 5"`, mixed subsets) with strict validation against negative, out-of-bounds, or inverted ranges.
4. **Flexible Naming Patterns:** Supports custom filename patterns with `{stem}`, `{page}`, `{page_count}`, and `{ext}` tokens (including zero-padding like `{page:02d}`). Single-page exports cleanly default to `{stem}.{ext}` without artificial `_page_1` suffixes. Directory traversal tokens (`/`, `\`, `..`) are rejected early.
5. **Atomic Placement & Collision Protection:** Each page is written to a volume-local temporary file and atomically moved into position via `os.replace()`. In-process reservations (`reserve_output_path`) ensure Windows-style collision avoidance (e.g., `_page_1 (2).png`) without overwriting existing files.
6. **Multi-Output Result Contract:** Extended `ConversionResult` with `output_paths: tuple[Path, ...]` and aggregate `output_bytes`, preserving 100% backward compatibility for single-file conversions (`output_path == output_paths[0]`).
7. **Failure Safety & Cancellation:** Cooperative cancellation is checked between pages and during rendering. On cancellation or failure, all partially created temporary files and outputs are immediately pruned from disk.
8. **Comprehensive Automated Verification:** Added 39 tests in [`tests/test_pdf_image_export.py`](file:///Z:/LocalShift/tests/test_pdf_image_export.py). Full test suite passes repository-wide with **442 passed, 3 skipped, 0 failed** in 2 minutes 5 seconds.

---

### 2. Architecture & Implementation

#### 1. PDF Image Exporter (`localshift.documents.pdf_image_exporter.PdfToImageExporter`)
Located in [`src/localshift/documents/pdf_image_exporter.py`](file:///Z:/LocalShift/src/localshift/documents/pdf_image_exporter.py):
- **Structural Preflight & Inspection:** Inspects input PDF structure using `PdfInspector.inspect()` to trap password-protected (encrypted), damaged/corrupt, or 0-page documents before rasterization starts.
- **Page Selection Parser (`parse_page_selection`):**
  - Canonicalizes `"all"`, integers, sequences, and strings into a sorted, de-duplicated tuple of 1-based page numbers.
  - Enforces page boundaries: rejects `page < 1`, `page > total_pages`, inverted ranges (`"5-2"`), or non-numeric tokens with `InvalidInputError`.
- **Option Validation (`validate_options`):**
  - `dpi`: Integer clamped between 72 and 400.
  - `quality`: Integer clamped between 1 and 100 (validated exclusively for JPEG targets).
  - `jpeg_background`: RGB 3-tuple (0–255) for alpha channel compositing onto white or custom background.
  - `output_pattern`: String validated to prohibit directory separators (`/`, `\`) or parent directory traversal (`..`). Multipage exports require `{page}` to prevent file clobbering.
- **Rendering & Output Placement (`export_pdf_to_images`):**
  - Iterates over selected pages with memory-bounded rendering via `PdfPageRenderer.render_page()`.
  - Converts rendered NumPy array to Pillow `Image` with zero Use-After-Free risk.
  - Generates final page names using pattern formatting.
  - Acquires collision-free reservations via `reserve_output_path()`.
  - Atomically writes each image via `mkstemp()` and `os.replace()`.
  - Tracks created files and reservations, ensuring clean rollback on cancellation or error.

#### 2. Adapter Extension (`localshift.documents.adapter.PdfDocumentAdapter`)
Located in [`src/localshift/documents/adapter.py`](file:///Z:/LocalShift/src/localshift/documents/adapter.py):
- Extended `_target_formats = frozenset({"txt", "docx", "png", "jpeg"})`.
- Registered routes: `("pdf", "png")`, `("pdf", "jpeg")`.
- Exposes route-specific options via `get_supported_options()`:
  - For `pdf` → `png`: `dpi`, `pages`, `output_pattern`.
  - For `pdf` → `jpeg`: `dpi`, `pages`, `output_pattern`, `quality`, `jpeg_background`.
- Dispatches image requests directly to `PdfToImageExporter.export_pdf_to_images()`.

#### 3. Core Engine Coordination (`localshift.converter.convert_request`)
Located in [`src/localshift/converter.py`](file:///Z:/LocalShift/src/localshift/converter.py):
- Detects self-placed/multi-output adapters (`src_key == "pdf" and target_key in ("png", "jpeg", "jpg")`).
- Avoids premature single-file path reservations or placeholder temp files when the adapter manages multi-output placements.
- Populates `output_paths` and total `output_bytes` from adapter result.

#### 4. Model Extension (`localshift.models.ConversionResult`)
Located in [`src/localshift/models.py`](file:///Z:/LocalShift/src/localshift/models.py):
- Added `output_paths: tuple[Path, ...] = ()`.
- `__post_init__` automatically populates `output_paths = (self.output_path,)` when omitted, guaranteeing backwards compatibility for all single-file conversion routes and callers.

#### 5. Preflight Option Validation (`localshift.planner.validate_conversion_options`)
Located in [`src/localshift/planner.py`](file:///Z:/LocalShift/src/localshift/planner.py):
- Validates `dpi`, `quality`, `pages`, and `output_pattern` during preflight checks before any conversion job starts.

---

### 3. Verification & Test Inventory

A dedicated test suite [`tests/test_pdf_image_export.py`](file:///Z:/LocalShift/tests/test_pdf_image_export.py) was implemented with 39 automated tests:

| Test Group | Tests | Coverage Focus | Result |
|---|---|---|---|
| **Capabilities & Routes** | 4 | `route_supported("pdf", "png")`, `route_supported("pdf", "jpeg")`, output formats query, option specs | **PASSED** |
| **Page Selection Parsing** | 10 | `"all"`, single page, ranges, comma lists, sequences, bounds checks, zero/negative, inverted ranges, invalid syntax | **PASSED** |
| **Option Validation & Preflight** | 5 | Valid options, DPI bounds, JPEG quality bounds, pattern traversal rejection, preflight validation | **PASSED** |
| **Single-Page Conversion** | 3 | PDF → PNG headers and PIL readability, PDF → JPEG headers, DPI scaling (72 vs 144 DPI dimension scaling) | **PASSED** |
| **Multipage Export & Naming** | 5 | All 3 pages exported, subset selection (`pages="1, 3"`), single page from multipage, custom pattern token substitution, missing `{page}` token error | **PASSED** |
| **Collision Avoidance** | 2 | Existing files protected with `(2)` suffix, multipage partial collisions handled independently per page | **PASSED** |
| **Cancellation & Cleanup** | 1 | Cooperative cancellation halts export and cleans up all partial temporary and output files | **PASSED** |
| **Error Handling & Security** | 6 | Encrypted PDF (`doc_10`), corrupt PDF (`doc_09`), blank page PDF (`doc_13`), 0-page PDF, 0-byte file, nonexistent source | **PASSED** |
| **High-Level API Integration** | 3 | `convert_image()` PNG wrapper, `convert_image()` JPEG wrapper, asynchronous `JobQueue` execution | **PASSED** |

#### Repository-Wide Regression Results
```powershell
$env:PYTHONPATH = "src"
py -3.14 -m pytest -o pythonpath=src
```
- **Total Tests Collected:** 445
- **Passed:** 442
- **Skipped:** 3 (symlink tests requiring Windows Developer Mode / Admin)
- **Failed:** 0
- **Duration:** 125.28s (2m 05s)

---

### 4. Changed Files Summary

| File | Type | Changes |
|---|---|---|
| `src/localshift/documents/pdf_image_exporter.py` | New File | `PdfToImageExporter` engine, `parse_page_selection()`, `validate_options()`, `export_pdf_to_images()`. |
| `src/localshift/models.py` | Modified | Added `output_paths: tuple[Path, ...]` to `ConversionResult` with auto-population post-init. |
| `src/localshift/converter.py` | Modified | Clean multi-output handling, avoids single-file pre-reservation collisions for batch image export. |
| `src/localshift/documents/adapter.py` | Modified | Added `("pdf", "png")` and `("pdf", "jpeg")` routes, option specs, and export dispatch. |
| `src/localshift/planner.py` | Modified | Added preflight validation for `dpi`, `quality`, `pages`, and `output_pattern`. |
| `src/localshift/documents/__init__.py` | Modified | Exported `PdfToImageExporter`. |
| `src/localshift/__init__.py` | Modified | Exported `PdfToImageExporter`. |
| `tests/test_converter.py` | Modified | Updated baseline tests to reflect that `pdf` → `png` is now a supported route. |
| `tests/test_pdf_extraction.py` | Modified | Updated capability discovery to assert `pdf` → `jpeg` is supported. |
| `tests/test_planning.py` | Modified | Updated supported route counts (25 with DOCX->PDF available, 24 baseline) and target formats for PDF. |
| `tests/test_pdf_image_export.py` | New File | 39 comprehensive tests for PDF to image rasterization, options, multipage, and security. |
| `docs/FORMAT_SUPPORT.md` | Modified | Updated route matrix (25 routes), option tables, and added Section 7 for PDF image export. |
| `docs/ARCHITECTURE.md` | Modified | Updated architecture diagram and added subsystem H (`PdfToImageExporter`). |
| `docs/TEST_PLAN.md` | Modified | Updated test inventory to 445 tests and added PDF image export test suite. |
| `docs/PROJECT_STATUS.md` | Modified | Marked LS-BE-010 complete, updated test counts and current status. |
| `TASKS.md` | Modified | Marked LS-BE-010 complete, updated test status and next milestone. |

---

### 5. Known Limitations & Remaining Risks

1. **Memory Ceiling on Extreme DPI:** Rendering a 2000-page document at 400 DPI requires substantial disk I/O and processing time. LocalShift safely bounds per-page rasterization to 16 MP and releases page bitmaps immediately, but long batch runs should be executed via `JobQueue` to avoid blocking main threads.
2. **Missing Token Warning vs. Error:** Omitting `{page}` in `output_pattern` when exporting multiple pages is strictly rejected with `InvalidInputError` to prevent pages from clobbering each other; when exporting a single page, `{page}` is optional.
3. **No PDF-to-Vector-Image:** This engine exports raster images (PNG, JPEG). Exporting PDF pages to vector graphics (SVG) is out of scope and deferred.
