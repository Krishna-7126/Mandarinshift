# LocalShift — Work Report: Milestone LS-BE-013
## Unified PySide6 GUI Integration & PDF Workbench UX

**Date:** 2026-10-25  
**Role:** Senior Python/PySide6 Desktop Engineer and QA Engineer  
**Status:** Completed & Verified  

---

### 1. Executive Summary

Milestone **LS-BE-013** delivers a unified, modern, minimal, and fully offline desktop interface for LocalShift built with **PySide6** (LGPL-3.0). It integrates all verified backend conversion and workbench engines into five dedicated desktop workflows without duplicating conversion logic, altering stable engines, or introducing backend dependencies on GUI libraries.

Key achievements:
1. **Five Dedicated Desktop Workflows (`localshift.gui`):**
   - **General File Converter (`FileConverterTab`):** Batch file queue supporting drag-and-drop, dynamic per-file target format dropdowns populated from `output_formats_for(path)`, output directory selection, and a batch options panel for OCR mode, DPI, JPEG quality, and page selection.
   - **Document Interchange: PDF ↔ DOCX (`DocxInterchangeTab`):** Direction toggle between PDF → DOCX (structured document extraction & local OCR) and DOCX → PDF (high-fidelity rendering) with real-time detection badge for available rendering backends (Microsoft Word COM or LibreOffice Headless).
   - **PDF → Images Rasterizer (`PdfRasterizeTab`):** Exports PDF pages as PNG (lossless) or JPEG (compressed) with configurable DPI (72–400), JPEG compression quality (1–100), page selection syntax (`all`, `1-3`, `1, 3, 5`), and custom naming patterns with token substitution.
   - **Images → PDF Multi-Image Assembly (`ImagesToPdfTab`):** Combines multiple raster images (`png`, `jpeg`, `webp`, `bmp`, `tiff`) into one ordered multipage PDF with interactive Move Up, Move Down, Remove, and Clear controls, plus page size (`original`, `a4`, `letter`), fit mode (`contain`, `cover`), orientation (`auto`, `portrait`, `landscape`), and point margin settings.
   - **PDF Workbench (`PdfWorkbenchTab`):** Dedicated page-level PDF manipulation interface supporting Merge (multi-document ordering), Split (burst pages to individual files), Extract (pull subset to new document), Reorder (resequence pages by index), and Rotate (90°, 180°, 270° with relative/absolute mode).
2. **Responsive Threading & Cooperative Cancellation:**
   - Long conversions run on `QThread` workers (`BatchConversionWorker`, `SingleTaskWorker`), keeping the Windows user interface fluid and responsive.
   - Cooperative cancellation checks (`cancel()`, `ConversionCancelledError`) allow users to safely halt execution without leaving orphaned files or unreleased reservations.
3. **Backend Isolation & Architecture Integrity:**
   - PySide6 is imported strictly within `localshift.gui` and `tests/test_gui.py`.
   - Core backend modules (`localshift`, `converter`, `formats`, `registry`, `adapters`, `documents`) have zero dependency on PySide6, verified by `test_converter.py:test_no_pyside6_import_on_backend_import`.
4. **Offline & Safety Guarantees:**
   - 100% offline, zero network telemetry, zero cloud calls, zero external runtime downloads.
   - Source immutability preserved (read-only input files, never mutated).
   - Collision protection via in-process reservations (`reserve_output_path`) and atomic temporary file replacement (`os.replace`).
5. **Comprehensive Verification:**
   - Added 30 dedicated automated GUI tests in [`tests/test_gui.py`](file:///Z:/LocalShift/tests/test_gui.py) covering window instantiation, tab switching, queue loading, reordering, options binding, worker threads, cancellation, and real end-to-end execution of conversions through the GUI layer.
   - Performed real Windows GUI smoke test on Python 3.14.3 (AMD64) verifying all 7 UI interaction checkpoints cleanly.
   - Full regression suite passes repository-wide with **552 passed, 3 skipped, 0 failed** in 1 minute 56 seconds.

---

### 2. Architecture & Implementation

#### 1. GUI Architecture & Theme
Located in [`src/localshift/gui.py`](file:///Z:/LocalShift/src/localshift/gui.py):
- **Branding & Visual Design:** Professional, clean Windows styling matching LocalShift's brand identity:
  - Primary accent: `#4f46e5` (indigo), hover `#4338ca`, active `#3730a3`.
  - Neutral backgrounds: `#f8fafc`, panel cards: `#ffffff`, subtle borders: `#e2e8f0`.
  - Rounded interactive elements (buttons 5px border-radius, tabs 6px border-radius, clean tables with muted headers).
- **Navigation Structure:** `MainWindow(QMainWindow)` hosts a `QTabWidget` containing 5 dedicated tabs:
  1. `FileConverterTab` ("File Converter")
  2. `DocxInterchangeTab` ("PDF ↔ DOCX")
  3. `PdfRasterizeTab` ("PDF → Images")
  4. `ImagesToPdfTab` ("Images → PDF")
  5. `PdfWorkbenchTab` ("PDF Workbench")
- **Global Drag-and-Drop:** Dropping files onto `MainWindow` automatically delegates to the active tab's `dropEvent` handler.

#### 2. Worker Thread Subsystem
- **`BatchConversionWorker(QThread)`:**
  - Manages sequential batch conversion queues without locking the UI.
  - Emits `item_done(row_idx, status, detail)` to update specific table rows as each job completes.
  - Emits `progress(completed, total)` to drive the progress bar smoothly.
  - Emits `finished(succeeded, failed, errors)` to trigger completion summaries.
  - Implements cooperative cancellation flag `_is_cancelled` polled via `cancel_check` callback in `convert_request()`.
- **`SingleTaskWorker(QThread)`:**
  - Generic background execution wrapper for single-document operations (PDF Workbench, Image Assembly, Document Interchange).
  - Emits `completed(success, message, paths)`.
  - Catches `ConversionCancelledError`, `ConversionError`, and unexpected exceptions with actionable error descriptions.

#### 3. Dedicated Workflow Tabs
- **`FileConverterTab`:**
  - Drag-and-drop table displaying File name, Human-readable size, Target Format `QComboBox`, Status, and Details/Path.
  - Target format dropdown dynamically populates with valid target formats using `output_formats_for(path)`.
  - Batch options panel with OCR mode selector, resolution DPI spinbox (72–400), JPEG quality spinbox (1–100), and page selection.
  - Output folder picker with "Same folder as source" default.
  - Non-blocking Convert and Cancel buttons.
- **`DocxInterchangeTab`:**
  - Radio toggle between PDF → DOCX and DOCX → PDF workflows.
  - Real-time renderer status badge calling `DocxToPdfRenderer.find_available_backend()` to show whether Microsoft Word COM or LibreOffice Headless is active.
  - File browse and destination folder selection.
- **`PdfRasterizeTab`:**
  - Format selector (PNG vs JPEG) dynamically enabling/disabling JPEG compression quality spinbox.
  - Configurable DPI, page range selection, and filename pattern (`{stem}_page_{page:02d}.{ext}`).
  - Direct delegation to `convert_request()` using `PdfDocumentAdapter` / `PdfToImageExporter`.
- **`ImagesToPdfTab`:**
  - Interactive table displaying assembly order (`#1`, `#2`, …), filename, and size.
  - Reordering controls: "Move Up", "Move Down", "Remove", "Clear All".
  - Layout controls: Page size (`original`, `a4`, `letter`), Fit mode (`contain`, `cover`), Orientation (`auto`, `portrait`, `landscape`), and Point margins (0–144 pt).
  - Direct delegation to `convert_images_to_pdf()`.
- **`PdfWorkbenchTab`:**
  - Operation selector dropdown (`Merge`, `Split`, `Extract`, `Reorder`, `Rotate`).
  - Dynamic panel visibility switching based on chosen operation:
    - `Merge`: Multi-PDF ordered queue with Move Up/Down controls and $\ge 2$ file validation.
    - `Split`: Page range selection and naming pattern with `{page}` token.
    - `Extract`: Comma-separated page list validation.
    - `Reorder`: Sequence validation for 1-based comma-separated integers.
    - `Rotate`: Angle dropdown (90°, 180°, 270°) and relative rotation checkbox.
  - Direct delegation to `merge_pdfs`, `split_pdf`, `extract_pdf_pages`, `reorder_pdf_pages`, and `rotate_pdf_pages`.

---

### 3. Verification & Test Results

#### 1. Automated GUI Test Suite ([`tests/test_gui.py`](file:///Z:/LocalShift/tests/test_gui.py))
30 dedicated tests covering all GUI components and workflows:
- **`TestMainWindow` (2 tests):** Window title, 5-tab structure, widget types.
- **`TestFileConverterTab` (4 tests):** Add files, target format combobox population via `output_formats_for`, remove/clear queue, duplicate path filtering, option defaults.
- **`TestDocxInterchangeTab` (3 tests):** Direction toggle visibility, backend status display, missing input validation.
- **`TestPdfRasterizeTab` (2 tests):** Format switch enabling/disabling quality, default settings.
- **`TestImagesToPdfTab` (3 tests):** Adding and reordering images (Move Up/Down), removing/clearing items, layout option defaults.
- **`TestPdfWorkbenchTab` (5 tests):** Dynamic operation switching, merge queue reordering, minimum 2-file merge validation, extract missing pages validation, reorder invalid integer validation.
- **`TestWorkers` (3 tests):** `SingleTaskWorker` execution, error handling with exception capture, `BatchConversionWorker` cooperative cancellation.
- **`TestWorkflowExecution` (8 tests):** Real end-to-end execution through the GUI layer for File Converter, PDF rasterize, Images → PDF assembly, Merge, Split, Extract, Reorder, and Rotate.

#### 2. Real Windows GUI Smoke Test ([`scripts/smoke_test_gui.py`](file:///Z:/LocalShift/scripts/smoke_test_gui.py))
Executed directly on Windows 11 AMD64 host:
- PySide6 Version: 6.12.0
- Python Version: 3.14.3 (AMD64)
- **Results:**
  - `Smoke Test [1/7]: MainWindow and 5 workflow tabs created successfully.`
  - `Smoke Test [2/7]: FileConverterTab added file with 5 target formats.`
  - `Smoke Test [3/7]: DocxInterchangeTab direction toggled and backend checked.`
  - `Smoke Test [4/7]: PdfRasterizeTab format selection and quality enabled.`
  - `Smoke Test [5/7]: ImagesToPdfTab queue loaded and verified.`
  - `Smoke Test [6/7]: PdfWorkbenchTab all 5 operations switched and verified.`
  - `Smoke Test [7/7]: Window closed cleanly and event loop flushed.`
  - `>>> ALL WINDOWS GUI SMOKE CHECKS PASSED SUCCESSFULLY! <<<`

#### 3. Backend PySide6 Isolation Test
- `test_converter.py:test_no_pyside6_import_on_backend_import`: **PASSED**.
- Confirms that importing `localshift`, `localshift.converter`, `localshift.formats`, and `localshift.cli` does NOT import `PySide6`.

#### 4. Full Regression Suite Results
Executed repository-wide test suite:
- **Command:** `py -3.14 -m pytest -o pythonpath=src`
- **Result:** **552 passed, 3 skipped, 0 failed** in 116.72s (1 minute 56 seconds).
- Skipped tests (3): Windows non-admin symlink privilege tests (standard Windows safety skip).

---

### 4. Changed & Added Files

| File | Change | Description |
|---|---|---|
| [`src/localshift/gui.py`](file:///Z:/LocalShift/src/localshift/gui.py) | Modified | Unified PySide6 desktop GUI with 5 dedicated workflow tabs, styling, and `QThread` workers. |
| [`tests/test_gui.py`](file:///Z:/LocalShift/tests/test_gui.py) | Created | 30 automated GUI unit and workflow integration tests. |
| [`scripts/smoke_test_gui.py`](file:///Z:/LocalShift/scripts/smoke_test_gui.py) | Created | Real Windows GUI smoke test script verifying UI lifecycle. |
| [`docs/FORMAT_SUPPORT.md`](file:///Z:/LocalShift/docs/FORMAT_SUPPORT.md) | Modified | Added Section 10 documenting GUI workflows and bumped version to 0.13.0. |
| [`docs/PROJECT_STATUS.md`](file:///Z:/LocalShift/docs/PROJECT_STATUS.md) | Modified | Added LS-BE-013 milestone, updated architecture overview, updated test counts (552 passed). |
| [`docs/TEST_PLAN.md`](file:///Z:/LocalShift/docs/TEST_PLAN.md) | Modified | Added GUI test scope and `tests/test_gui.py` to inventory. |
| [`TASKS.md`](file:///Z:/LocalShift/TASKS.md) | Modified | Marked LS-BE-013 complete; updated metrics. |
| [`docs/reports/LS-BE-013-work-report.md`](file:///Z:/LocalShift/docs/reports/LS-BE-013-work-report.md) | Created | Work report for milestone LS-BE-013. |

---

### 5. Limitations & Remaining Issues

1. **Physical Display Interaction:** Automated GUI testing was executed in offscreen mode (`QT_QPA_PLATFORM=offscreen`) to run reliably in non-interactive/CI environments. Real visual rendering of Qt widgets was verified via smoke test lifecycle validation.
2. **PySide6-WebEngine Footprint:** Installing `PySide6>=6.7` meta-package downloads optional WebEngine wheels (~130 MB). While LocalShift does not use WebEngine (relying purely on QtWidgets/QtCore/QtGui), production installers can package exclusively `PySide6-Essentials` to minimize download size.
3. **Word COM Elevation:** Word COM automation for DOCX rendering requires standard user desktop session privileges and cannot run inside headless services without desktop session access.
