# LocalShift — Work Report: Milestone LS-BE-012
## PDF Workbench Engine: Merge, Split, Reorder & Rotate

**Date:** 2026-10-25  
**Role:** Senior Backend Engineer, PDF Systems Architect, and QA Engineer  
**Status:** Completed & Verified  

---

### 1. Executive Summary

Milestone **LS-BE-012** delivers a reliable, high-performance, fully offline **PDF Workbench Engine** for LocalShift. It introduces lossless structural manipulation for PDF documents—including multi-document merging, page extraction and splitting, 1-based sequence reordering, and arbitrary 90°/180°/270° page rotations—without altering existing format conversion routes.

Key achievements:
1. **Four Core Structural Operations:**
   - **Merge (`merge_pdfs`):** Combines multiple PDF documents in an explicit user-defined sequence while preserving page media boxes, crop boxes, graphics, annotations, and rotation angles.
   - **Split (`split_pdf`):** Splits PDF documents into individual single-page PDF files or subsets with flexible naming patterns (`{stem}`, `{page}`, `{page_count}`, `{ext}`).
   - **Extract (`extract_pdf_pages`):** Extracts arbitrary page subsets (e.g. `"1-3, 5"`) into a single new PDF document without raster re-encoding or fidelity degradation.
   - **Reorder (`reorder_pdf_pages`):** Rearranges pages according to a validated 1-based index permutation (e.g. `[3, 1, 2]`), verifying bounds against total page count.
   - **Rotate (`rotate_pdf_pages`):** Rotates selected or all pages by 90°, 180°, or 270° (including negative angles like -90°), supporting both relative (`(current + angle) % 360`) and absolute rotation modes.
2. **Offline-First & Permissively Licensed:** Powered exclusively by Google PDFium via `pypdfium2` (Apache-2.0 / BSD-3). 100% offline, zero network telemetry, zero AGPL or non-commercial dependencies (no PyMuPDF/fitz).
3. **Immutability & Concurrency Safety:**
   - Input files are opened strictly read-only and never modified in place.
   - Output paths are chosen and locked using in-process collision reservations (`reserve_output_path`) to prevent file clobbering.
   - Output writes execute into volume-local temporary files and replace targets atomically via `os.replace()`.
4. **Preflight Inspection & Resource Bounds:**
   - Corrupt, password-protected (encrypted), non-PDF, or 0-page files are rejected cleanly before disk writes.
   - Enforces a combined 2000-page limit (`MAX_PAGES_LIMIT`) and 250 MiB per-file ceiling (`MAX_INPUT_BYTES`).
5. **CLI & GUI Integration:**
   - Added `localshift pdf` subcommands: `merge`, `split`, `extract`, `reorder`, and `rotate`.
   - Updated GUI open dialog filter to accept PDF and Word files.
6. **Automated Verification:** Added 41 dedicated automated tests in [`tests/test_pdf_workbench.py`](file:///Z:/LocalShift/tests/test_pdf_workbench.py). Full regression suite passes repository-wide with **522 passed, 3 skipped, 0 failed** in 2 minutes 7 seconds.

---

### 2. Architecture & Implementation

#### 1. PDF Workbench Subsystem (`localshift.documents.pdf_workbench`)
Located in [`src/localshift/documents/pdf_workbench.py`](file:///Z:/LocalShift/src/localshift/documents/pdf_workbench.py):
- **Input Validation (`_validate_pdf_input`):** Checks existence, regular file status, 250 MiB size ceiling, magic bytes (`%PDF-`), and structural readability and encryption status via `PdfInspector`.
- **Destination Conflict Guard (`_check_source_conflict`):** Compares resolved paths to guarantee that an output path never matches any source input, raising `DestinationConflictError` before reservations occur.
- **Merge Operation (`merge` / `merge_pdfs`):**
  - Iterates through `sources` in explicit given order.
  - Combines pages using `merged_doc.import_pages(src_doc)`.
  - Enforces `MAX_PAGES_LIMIT = 2000`.
  - Atomically writes to destination (`{first_stem}_merged.pdf` or custom path).
- **Split Operation (`split` / `split_pdf`):**
  - Parses page selection using `PdfToImageExporter.parse_page_selection`.
  - Validates output pattern against directory traversal (`/`, `\`, `..`) and ensures `{page}` token exists when multiple pages are split.
  - Writes each page as a single-page document atomically with reservation tracking.
  - Cleans up all generated files on cancellation or failure.
- **Extract Operation (`extract` / `extract_pdf_pages`):**
  - Creates a new PDF document and imports only the specified pages in order.
  - Saves atomically to `{stem}_extracted.pdf` or specified path.
- **Reorder Operation (`reorder` / `reorder_pdf_pages`):**
  - Validates `page_order`: non-empty sequence of integers where $1 \le p \le \text{total\_pages}$.
  - Imports pages in the requested sequence `[p - 1 for p in page_order]`.
  - Saves atomically to `{stem}_reordered.pdf` or specified path.
- **Rotate Operation (`rotate` / `rotate_pdf_pages`):**
  - Validates rotation angle: must be integer multiple of 90 degrees (modulo 360 $\in \{0, 90, 180, 270\}$).
  - Adjusts rotation per page via `page.set_rotation()`.
  - Saves atomically to `{stem}_rotated.pdf` or specified path.

#### 2. Command-Line Interface (`localshift.cli`)
Located in [`src/localshift/cli.py`](file:///Z:/LocalShift/src/localshift/cli.py):
- Added `pdf` subcommand with nested subparsers:
  - `localshift pdf merge <inputs...> [-o <output>] [--output-dir <dir>]`
  - `localshift pdf split <input> [--pages <pages>] [--output-dir <dir>] [--pattern <pattern>]`
  - `localshift pdf extract <input> --pages <pages> [-o <output>] [--output-dir <dir>]`
  - `localshift pdf reorder <input> --order <order> [-o <output>] [--output-dir <dir>]`
  - `localshift pdf rotate <input> --angle <angle> [--pages <pages>] [-o <output>] [--output-dir <dir>]`

---

### 3. Verification & Test Results

#### 1. Targeted PDF Workbench Suite (`tests/test_pdf_workbench.py`)
41 tests covering all operations:
- **Merge (10 tests):** 2-document merge, 3-document explicit order, 1-document trivial merge, empty sources error, missing file error, corrupted file error, bad magic bytes error, collision avoidance (` (2).pdf`), destination conflict error, and cancellation rollback.
- **Split (7 tests):** Split all pages, split subset (`1, 3`), custom pattern formatting (`part{page:02d}`), pattern missing `{page}` error, path traversal pattern error, out-of-bounds page error, and cancellation cleanup.
- **Extract (5 tests):** Extract subset, extract single page, extract range, inverted range error (`3-1`), and destination conflict error.
- **Reorder (7 tests):** Page permutation (`[3, 1, 2]`), subset reorder (`[2, 1]`), empty sequence error, out-of-bounds error, index 0 error, non-integer error, and source file immutability check.
- **Rotate (7 tests):** Relative +90° rotation, specific page 180° rotation, negative angle -90° rotation, absolute 90° rotation, invalid angle (45°) error, non-integer angle error, and source file immutability check.
- **CLI Integration (5 tests):** Live invocation of `localshift pdf merge`, `split`, `extract`, `reorder`, and `rotate` via `sys.argv` and capsys capture.

#### 2. Full Regression Test Suite
Executed repository-wide:
```powershell
py -3.14 -m pytest -o pythonpath=src
```
**Results:** **522 passed, 3 skipped, 0 failed** in 127.30 seconds (0:02:07).

Skipped tests:
- 3 Windows non-admin symlink creation tests (expected behavior on standard Windows privilege levels).

---

### 4. Changed Files

| File | Change Summary |
|---|---|
| [`src/localshift/documents/pdf_workbench.py`](file:///Z:/LocalShift/src/localshift/documents/pdf_workbench.py) | **New file**: `PdfWorkbench` implementation with merge, split, extract, reorder, rotate, preflight checks, and atomic placement. |
| [`tests/test_pdf_workbench.py`](file:///Z:/LocalShift/tests/test_pdf_workbench.py) | **New file**: 41 unit, integration, and CLI tests. |
| [`src/localshift/cli.py`](file:///Z:/LocalShift/src/localshift/cli.py) | Added `pdf` subcommand with `merge`, `split`, `extract`, `reorder`, and `rotate`. |
| [`src/localshift/gui.py`](file:///Z:/LocalShift/src/localshift/gui.py) | Updated file dialog filter to accept PDF and DOCX files. |
| [`src/localshift/__init__.py`](file:///Z:/LocalShift/src/localshift/__init__.py) | Exported `PdfWorkbench`, `merge_pdfs`, `split_pdf`, `extract_pdf_pages`, `reorder_pdf_pages`, `rotate_pdf_pages`. |
| [`src/localshift/documents/__init__.py`](file:///Z:/LocalShift/src/localshift/documents/__init__.py) | Exported workbench symbols. |
| [`docs/FORMAT_SUPPORT.md`](file:///Z:/LocalShift/docs/FORMAT_SUPPORT.md) | Bumped version to 0.12.0, added Section 9 PDF Workbench Subsystem, renumbered sections. |
| [`docs/ARCHITECTURE.md`](file:///Z:/LocalShift/docs/ARCHITECTURE.md) | Bumped version to 0.12.0, added Subsystem J PDF Workbench Engine. |
| [`docs/TEST_PLAN.md`](file:///Z:/LocalShift/docs/TEST_PLAN.md) | Bumped version to 0.12.0, updated test metrics (525 collected, 522 passed), added test inventory row. |
| [`docs/PROJECT_STATUS.md`](file:///Z:/LocalShift/docs/PROJECT_STATUS.md) | Bumped version to 0.12.0, marked LS-BE-012 Complete, updated architecture and next milestone. |
| [`TASKS.md`](file:///Z:/LocalShift/TASKS.md) | Marked LS-BE-012 Complete, updated task tracker. |

---

### 5. Licensing & Limitations

- **Licensing:** Uses `pypdfium2` (Apache-2.0 / BSD-3) wrapping Google PDFium. 100% compliant with LocalShift's permissive offline architecture. No AGPL dependencies.
- **Zero In-Place Mutation:** Input source files are strictly immutable and never modified or overwritten.
- **Resource Ceilings:** Combined page limits (2000 pages) and per-file size limits (250 MiB) prevent denial-of-service and memory exhaustion.
