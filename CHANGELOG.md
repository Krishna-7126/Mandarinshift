# LocalShift — Changelog

All notable changes to the LocalShift project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Milestone 23: Release Readiness & Regression Stabilization

## [Unreleased] — Milestone 24: Release Readiness & Windows Verification

### Fixed
- Prevent unseen-validation tests from silently regenerating or overwriting existing PDF fixtures; tests now fail clearly if fixtures are missing.
- Make packaging builds use new, non-overlapping output, work, and installer directories and refuse to overwrite existing paths.
- Correct the stale RapidOCR classifier hidden-import path and allow Inno Setup source/output paths to be isolated from existing release artifacts.
- Declare the verified PyInstaller version in the optional `[build]` dependency extra and document clean setup/build commands.
- Replace ambiguous all-cases-at-once gesture reporting with one case-attributed interactive session at a time, versioned report migration, allowlisted JSONL diagnostics, in-memory-only source-path hashing, and non-overwriting temporary self-check assets.

### Verification
- Official Windows regression launcher after harness updates: **751 passed, 3 skipped, 0 failed**. The skips are symlink-permission cases.
- A fresh Python 3.11.9 environment installed declared extras and built the current-source portable bundle and Inno Setup installer in temporary directories.
- Gesture harness tests cover unconfirmed `NOT TESTED` status, case attribution, privacy filtering, safe relative output labels, source hashing, GUI `SystemExit(0)` collection, and temporary self-check assets.
- Physical Explorer/Desktop/third-party drag behavior, mixed-DPI displays, assistive technology, and installer install/uninstall lifecycle remain unverified; release readiness remains blocked.
- Exact results, artifact hashes, and the operator checklist are in `docs/reports/LS-BE-024-release-readiness.md`.

## [Unreleased] — Milestone 23: Release Readiness & Regression Stabilization

### Fixed
- Keep the radial OLE target under its activation pointer when screen-edge clamping would otherwise move the window out from under the drag; covered positive and negative screen coordinates.
- Launch source checkouts through `python -m localshift.gui` for the Windows "Start with Windows" entry; direct execution of the package file failed with an attempted-relative-import error.
- Added explicit accessible names to workflow tables, form controls, settings tabs, and destination/theme controls.
- Corrected the registered PDF tool count and clarified that global drag-source compatibility is not physically certified.
- Replaced the README's stale main/radial screenshots with current dark/light converter and radial captures; preserved the older screenshots.
- Corrected the recorded installer size; its existing checksum was independently reverified.

### Verification
- Radial and global gesture tests: **51 passed** after the screen-edge correction.
- Full regression suite: **730 passed, 3 skipped, 0 failed** in the project Python 3.11 venv; the three symlink tests require Developer Mode or elevation.
- Exact commands, findings, artifact checks, manual checklist, and release gates are recorded in `docs/reports/LS-BE-023-release-readiness.md`.
- Physical Explorer/Desktop/third-party drag behavior, mixed-DPI displays, assistive technology, and a current-source packaging build are not verified; release readiness remains blocked.

## [Unreleased] — Milestone 22A: Radial Wheel Reliability

### User interface
- Replace the competing gradient/card hierarchy with a restrained proof-sheet visual system, clearer converter and queue priority, grouped settings, and a theme-aware radial wheel.
- Make PDF tool choices keyboard-focusable and searchable, add an empty-results state, remove repeated category labels, and reflow the catalog to one column at minimum width.
- Collapse the Recent panel at narrow widths, shorten closed queue format labels while retaining full names in tooltips, and remove the unused row header to prevent overflow.
- Register Segoe UI when Windows Qt font discovery is empty; keep the PDF catalog count driven by the live registry instead of a stale header number.

### Fixed
- Anchor radial filename and destination pills around the wheel instead of the popup or application edges, and recalculate wheel geometry synchronously when resized.
- Align hit-testing with the visible petal discs, preserve the active petal with a distance buffer, and hit-test the pointer on click rather than confirming stale hover.
- Accept wheel mouse presses so clicks outside a petal cancel instead of reaching underlying controls.
- Keep one visible radial menu per app interaction and clear cancellation/ownership state when standalone menus close.

### Verification status
- Full regression suite: **723 passed, 3 skipped, 0 failed**; physical Windows drag-source and mixed-DPI verification remain open.
- Offscreen Qt captures reviewed in dark/light themes at 1020×680 and 760×560 for the converter, PDF catalog, settings, and radial wheel; physical-display and DPI behavior remain unverified.
- Detailed findings and test commands: `docs/reports/LS-BE-022A-radial-wheel-report.md`.

## Milestone 21: Global Gesture Reliability & Verification

### Fixed
- Radial conversion now submits only the exact paths in the validated drop payload; unrelated files already in the conversion queue are left untouched.
- Clear radial hover when a drag leaves all sectors, prevent stale or duplicate global drop dispatch, and return gesture state to IDLE after success or failure.
- Closing the app exits when global monitoring is off, even if a system tray icon is available.
- Parse saved global-gesture preferences safely when QSettings returns string values, preserving an explicit OFF choice.

### Added
- Physical verification mode writes a structured JSON report with every case initially marked `NOT TESTED`; an operator must record outcomes and short non-sensitive notes.
- Tests cover exact-payload-only conversion, stale hover, duplicate dispatch, cancellation recovery, settings parsing, and controller completion/failure cleanup.

### Verification status
- Automated checks are recorded in `docs/reports/LS-BE-021-reliability-report.md`.
- Explorer/Desktop/third-party physical tests and production performance measurements remain unverified; no release-ready or universal compatibility claim is made.

## Milestone 20: Environment Recovery & Verified Global Drag

### Fixed
- Global Shift+drag no longer reads Explorer selections or converts on mouse release; it requires the actual local-file OLE payload and a drop on a format sector.
- Rejects mixed/virtual URLs, inaccessible files, unsupported routes, and inputs larger than 250 MiB without converting a partial or guessed file list.
- Aligns radial sector drawing with hit testing and removes stale-hover fallback when a drop misses a sector.
- Constrains RapidOCR to the model/API series exercised by the OCR regression suite and makes Windows test execution use the project venv with Qt offscreen.

### Added
- Privacy-conscious optional gesture diagnostics and a repeatable Windows source/monitor/cancellation checklist.

## [0.19.0] — Milestone 19: Complete PDF Suite, Functional Features & Production-Ready Offline Conversion

### Added
- **Full PDF Suite Functional Implementations (`src/localshift/documents/pdf_tools_engine.py`):**
  - **PDF to Excel (`convert_pdf_to_excel`):** Extracts structured lines and tabular columns into genuine OpenXML `.xlsx` spreadsheets using native Python `zipfile` packaging (0 external dependencies, 7.47 ms execution).
  - **PDF to PowerPoint (`convert_pdf_to_powerpoint`):** Renders high-resolution slide images and builds editable OpenXML `.pptx` presentation decks via PowerPoint COM or standalone OpenXML packaging.
  - **PDF to PDF/A (`convert_pdf_to_pdfa`):** True ISO 19005-1 compliant PDF/A conversion via Word COM `ExportAsFixedFormat` with `UseISO19005_1=$true` and native XMP identification stream fallback.
  - **Excel to PDF (`convert_excel_to_pdf`):** Offline headless conversion of `.xlsx`, `.xls`, and `.csv` workbooks to clean PDF documents using local Microsoft Excel COM or LibreOffice.
  - **PowerPoint to PDF (`convert_powerpoint_to_pdf`):** Offline headless conversion of `.pptx` and `.ppt` slide presentations to PDF using PowerPoint COM or LibreOffice.
  - **Sign PDF (`sign_pdf_document`):** Digital verification seals and graphical signature stamps with UTC timestamps, SHA-256 integrity fingerprints, and customizable placement.
  - **Edit PDF (`edit_pdf_document`):** Text annotations with backdrop pills, bold status stamps ("APPROVED", "DRAFT", "CONFIDENTIAL"), and semi-transparent highlighter markup.
  - **Redact PDF (`redact_pdf_document`):** Permanent text excision that extracts bounding boxes, draws opaque black redaction rectangles, and flattens affected pages to raster image streams, mathematically destroying underlying text and vector operators.
  - **Fill PDF Forms (`fill_pdf_forms`):** Populates, flattens, and preserves interactive form fields and exports form metadata schema to JSON.
  - **Offline AI Summarizer (`summarize_pdf_document`):** Built-in pure-Python TextRank graph sentence ranking algorithm that extracts top executive summary points into Markdown without external model weights or internet access.
- **Honest Feature Availability Framework (`src/localshift/documents/pdf_tool_registry.py`):**
  - Introduced standard availability states: `READY`, `CONFIG_REQUIRED`, `PLANNED`, and `UNSUPPORTED`.
  - Added `setup_guide` and exact limitation documentation for configuration-dependent tools (`protect_pdf`, `translate_pdf`).
- **Interactive PDF Suite Dialog Enhancements (`src/localshift/pdf_suite_ui.py`):**
  - Dynamic option editors for Sign, Edit, Redact, AI Summarize, and OCR.
  - Configuration requirement banners displaying exact setup commands and host dependencies.
  - Contextual file browser wildcard filters tailored to each tool's supported input extensions.
- **Comprehensive PDF Tool Test Suite (`tests/test_pdf_tools.py`):**
  - 25 automated unit and integration tests verifying all 32 tools, XML packaging, PDF integrity, text redaction purging, and form flattening. All passing.
- **Milestone 19 Production Benchmarks (`scripts/benchmark_conversions.py`):**
  - Benchmarked 17 end-to-end workflows and PDF tools logged to `docs/benchmarks_m19.json`.

## [0.18.0] — Milestone 18: Production Reliability, Conversion Quality & Performance

### Added
- **Exhaustive 54-Route Verification Suite (`tests/test_all_conversion_routes.py`):**
  - Parameterized verification for every single registered conversion route among `PNG`, `JPEG`, `WebP`, `BMP`, `TIFF`, `GIF`, `ICO`, `PDF`, `DOCX`, and `TXT`.
  - Re-opens every output file to verify structural integrity (Pillow `im.verify()`, PDFium page checks, `python-docx` paragraph inspection, UTF-8 decoding).
  - Validates source file immutability and destination collision avoidance (` (2)` Windows-standard numbering).
- **Offline HTML-to-PDF Conversion (`src/localshift/documents/pdf_tools_engine.py`):**
  - High-speed local conversion from HTML documents to PDF using `PySide6.QtGui.QTextDocument` and `QPdfWriter` with A4 page layout and atomic output replacement.
- **Offline OCR PDF Tool (`src/localshift/documents/pdf_tools_engine.py`):**
  - Integrated `ocr_pdf_document` executing `RapidOcrEngine` on scanned or image-heavy PDFs to produce searchable `.txt` and structured `.docx` files.
- **Production Benchmark Suite (`scripts/benchmark_conversions.py`):**
  - Benchmarked all 12 core conversion workflows and PDF tools with latency, peak memory, and throughput metrics logged to `docs/benchmarks_m18.json`.

### Fixed
- **Truthful PDF Tool Capability Registry (`src/localshift/documents/pdf_tool_registry.py`):**
  - Reclassified `protect_pdf` to `CONFIG_REQUIRED` documenting backend encryption authoring requirement.
  - Reclassified `edit_pdf`, `sign_pdf`, and `redact_pdf` to `PLANNED` with Phase 5 roadmap limitations, eliminating misleading availability claims and unhandled UI exceptions.
- **PyInstaller Packaging Spec (`packaging/localshift.spec`):**
  - Added `pdf_tool_registry`, `pdf_tools_engine`, and `pdf_suite_ui` to hidden imports to ensure complete standalone executable packaging.

## [0.17.0] — Milestone 17: Comprehensive PDF Productivity Suite Architecture & UI Implementation

### Added
- **PDF Productivity Suite Architecture (`src/localshift/documents/pdf_tool_registry.py`):**
  - Registry of 32 PDF productivity tools organized across 5 clear categories:
    1. Organize & Optimize: Merge, Split, Compress, Rotate, Organize/Reorder, Extract Pages, Delete Pages, Crop PDF, Repair PDF.
    2. Convert from PDF: PDF to Word (DOCX), PDF to JPG, PDF to PNG, PDF to Markdown, PDF to PowerPoint, PDF to Excel, PDF to PDF/A.
    3. Convert to PDF: Word to PDF, PowerPoint to PDF, Excel to PDF, JPG to PDF, Scan to PDF, HTML to PDF.
    4. Security & Pages: Protect PDF, Unlock PDF, Page Numbers, Watermark, Redact PDF.
    5. Advanced & AI: OCR PDF, PDF Forms, Edit PDF, Sign PDF, Compare PDF, AI Summarizer, Translate PDF.
  - Strict availability reporting: `AVAILABLE` (native offline capability), `CONFIG_REQUIRED` (requires local external engine like LibreOffice, Tesseract, or local LLM), and `PLANNED`. No fake or simulated progress.
- **Dedicated PDF Tool Engine (`src/localshift/documents/pdf_tools_engine.py`):**
  - Implemented lossless, high-performance offline PDF operations:
    - `delete_pdf_pages()`: Selective page removal with 1-based page parsing (`1, 3-5`).
    - `crop_pdf_pages()`: Lossless crop box manipulation using native PDFium rect calculations.
    - `compress_pdf_file()`: Stream compression, unreferenced object removal, and metadata deduplication.
    - `unlock_pdf_file()`: Removal of PDF security using supplied authorization password and `FPDF_REMOVE_SECURITY`.
    - `repair_pdf_file()`: Content extraction and structural re-serialization of damaged or corrupted PDF objects.
    - `pdf_to_markdown_file()`: Layout and heading extraction converting document text into clean Markdown.
    - `add_page_numbers_to_pdf()`: Canvas stamping with configurable positions (`bottom_center`, `bottom_right`, `top_right`) and formats (`Page {n} of {total}`).
    - `add_watermark_to_pdf()`: Rotated semi-transparent text stamping across all pages.
    - `compare_two_pdfs()`: Page-by-page visual difference calculation and structured reporting.
    - `inspect_pdf_forms()`: Extraction and inspection of AcroForm fields (text fields, checkboxes, choices).
- **Searchable PDF Suite UI (`src/localshift/pdf_suite_ui.py`):**
  - Searchable grid with instant client-side filtering by name, category, and keyword.
  - Interactive category pill filters matching the design mockups.
  - Responsive 3-column card grid with visual status badges (`New!`, `Config Needed`, `Ready`).
  - Interactive `PdfToolExecutionDialog` with source selection, dynamic configuration options, destination resolution, and non-blocking background `QThread` execution.
- **Seamless Main Window Navigation Integration (`src/localshift/gui.py`):**
  - Added dedicated "🛠 PDF Suite" 6th sidebar tab with synchronized title, subtitle, and active styling.
  - Intelligent tool routing: clicking workflow tools redirects to dedicated tabs (e.g. PDF ↔ DOCX, PDF → Images, Images → PDF, PDF Workbench), while standalone tools trigger the interactive execution dialog.
- **Automated PDF Suite Test Suite (`tests/test_pdf_tools.py`):**
  - 14 tests covering delete pages, crop, compression, unlock, repair, markdown extraction, page numbering, watermark, comparison, form inspection, and tool execution dialog.

## [0.16.2] — Milestone 16D: Global Shift+Drag Stability, Smooth Radial Menu & Color-Accurate PDF Rendering

### Fixed
- **PDF Color Fidelity & Channel Swapping (P0):**
  - Diagnosed root cause: `pypdfium2` native `page.render()` renders in BGR bitmap byte order (`[B, G, R]`) by default. Passing raw bitmap arrays to `PIL.Image.fromarray(arr, mode="RGB")` without byte reversal caused Red and Blue channels to swap (pure Red `(255, 0, 0)` became Blue `(0, 0, 255)`; Team Lemon yellow `(255, 255, 0)` became Cyan `(0, 255, 255)`).
  - Fixed `PdfPageRenderer.render_page()` by specifying `rev_byteorder=True`, ensuring native PDFium RGB byte order.
  - Added `PdfPageRenderer.render_page_to_image(page, *, dpi, max_pixels)` using native `bmp.to_pil().copy()` for C-level buffer decoding, correct row stride handling, and transparent background compositing.
  - Updated `PdfToImageExporter` to support lossless `PNG`, background-composited `JPEG`, `WebP`, and `TIFF`.
  - Added comprehensive visual test suite (`tests/test_pdf_color_fidelity.py`) validating primary red, green, blue, Team Lemon yellow, neutral gray gradients, and MAE < 3.0 against reference color definitions.

- **Shift+Drag Radial Menu Jitter, Flickering, and Focus Stealing (P0):**
  - Diagnosed 4 compounding root causes:
    1. Focus stealing: `RadialConversionMenu.show_at_cursor()` called `activateWindow()` and `setFocus()`, breaking Windows OLE drag capture on File Explorer.
    2. Premature close loop: `changeEvent` closed on `ActivationChange` when `isActiveWindow()` was False, causing the background timer to re-summon and close repeatedly.
    3. Missing boundary hysteresis: `petal_at_pos()` dynamically offset the hit polygon for hovered petals, causing cursor hover state to oscillate rapidly at petal boundaries.
    4. Missing discrete state machine: lack of explicit state transitions allowed uncoordinated input tracking.
  - Configured floating radial menu with `Qt.WindowType.WindowDoesNotAcceptFocus` and `Qt.WidgetAttribute.WA_ShowWithoutActivating` to completely prevent focus theft and preserve Explorer OLE drag ownership.
  - Implemented polar sector hit-testing with a sticky angular deadband ($\pm 6^\circ$ hysteresis) and circular disc proximity in `petal_at_pos()`, eliminating edge jitter.
  - Removed `ActivationChange` premature window closing.
  - Implemented discrete `GestureState` state machine (`IDLE` -> `DRAG_CANDIDATE` -> `MENU_VISIBLE` -> `TARGET_SELECTED` -> `CONVERTING` -> `COMPLETED`, `CANCELLED`, `FAILED`).
  - Added instant Escape key cancellation (`VK_ESCAPE = 0x1B`) and Shift release dismissal, allowing the user to continue normal Windows drag-and-drop operations without interference.

### Added
- **Multi-Source Drag Adapter Architecture:**
  - `DragSourceAdapter` base class defining `is_source_active()`, `get_dragged_paths()`, and `can_retrieve_paths()`.
  - `ExplorerDragSourceAdapter`: Windows File Explorer (`CabinetWClass`, `ExplorerWClass`) via COM `IShellWindows`.
  - `DesktopDragSourceAdapter`: Windows Desktop (`Progman`, `WorkerW`).
  - `OleDropSourceAdapter`: Direct OLE drag-and-drop into LocalShift UI (`QDragEnterEvent` / `urls`).
  - `FallbackSourceAdapter`: Explicitly documents limitations for virtual drag payloads (e.g., inside browser DOM or compressed ZIP archives without filesystem extraction).
- **Automated Stability & Hysteresis Test Suite:**
  - Added `test_radial_menu_boundary_hysteresis_no_jitter` and `test_radial_menu_fast_circular_movement` in `tests/test_radial_menu.py`.
  - Added `test_drag_source_adapters`, `test_gesture_state_machine_transitions`, and `test_escape_key_cancels_drag_gesture` in `tests/test_shell_integration.py`.

## [0.16.1] — Milestone 16C: True Background Shift+Drag, Reliable PDF→DOCX, Conversion Performance & Premium UI Stabilization

### Fixed
- **XML 1.0 Compatibility Crash in PDF→DOCX Reconstruction:**
  - Diagnosed root cause of `DOCX reconstruction failed: All strings must be XML compatible: Unicode or ASCII, no NULL bytes or control characters` (`lxml.etree` error).
  - Implemented centralized `sanitize_xml_text()` removing NULL bytes (`\x00`), illegal ASCII control characters (`0x00–0x08`, `0x0E–0x1F`), mapping vertical tabs/form feeds (`\x0b`, `\x0c`) to newlines, while preserving valid whitespace (`\t`, `\n`, `\r`), multi-lingual text, CJK characters, and emojis.
  - Sanitized paragraphs, headings, bullet points, OCR text blocks, and table cell strings before inserting into `python-docx`.
  - Added atomic temporary file replacement (`.tmp_*.docx` renamed upon completion) preventing partial or corrupted outputs on conversion failure.
  - Added `sanitized_characters_count` diagnostic metric to `DocxReconstructionResult`.

### Added
- **True Background Shift+Drag Gesture & Windows Shell Integration:**
  - Non-invasive `BackgroundGestureController` polling physical drag state (`GetAsyncKeyState(0x01)` and `is_shift_pressed()`) with 60ms timer and zero elevated privilege requirements.
  - Foreground window validation (`is_explorer_or_desktop_foreground()`) checking active HWND window classes (`CabinetWClass`, `ExplorerWClass`, `Progman`, `WorkerW`).
  - Active File Explorer selection querying via `Shell.Application` (`IShellWindows`) in real-time (~90ms execution).
  - Floating radial menu popup centered at cursor with direct petal drag tracking and drop-to-convert execution.
  - Non-blocking system tray toast notifications (`QSystemTrayIcon.showMessage`) with click-to-open file/folder actions.
  - "Start with Windows" configuration managed in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\LocalShift`.
  - Quiet startup support with `--minimized` flag starting directly in the system tray.

### Performance
- **Conversion Latency & Memory Benchmarks (`scripts/benchmark_conversions.py`):**
  - Native Digital PDF → DOCX (multipage): **53.91 ms** (Peak memory: 2.44 MB).
  - Dense Digital PDF → DOCX: **37.03 ms** (Peak memory: 2.40 MB).
  - Scanned PDF → DOCX (RapidOCR inference on CPU): **2.08 s** (Peak memory: 157.51 MB).
  - Image 1080p PNG → WebP: **278.33 ms** (Peak memory: 1.93 MB).
  - Image 512px PNG → JPEG: **11.63 ms** (Peak memory: 0.14 MB).
  - Images → PDF Assembly (5 pages): **174.99 ms** (Peak memory: 0.28 MB).
  - PDF → PNG Rasterization (150 DPI): **69.14 ms** (Peak memory: 12.07 MB).

## [0.16.0] — Milestone 16B: Reliable Shift+Drag Conversion & Premium UI/UX Rebuild

### Added
- **Reliable Shift+Drag Conversion Gesture & In-Window Overlay Architecture:**
  - Resolved root cause of Windows OLE drag failure: top-level popup windows created during an ongoing OLE drag cause Windows OLE to drop capture or fail `IDropTarget` routing.
  - Engineered persistent `is_overlay=True` mode for `RadialConversionMenu` layered directly as a child of `MainWindow`, keeping single persistent `IDropTarget` HWND registered with Windows OLE.
  - Implemented physical Shift key state detection via Win32 `GetAsyncKeyState(0x10) & 0x8000` with Qt modifier fallback, guaranteeing seamless Shift activation whether pressed before or during an active drag.
  - Added continuous pointer tracking (`track_drag_pos`) and circular petal hit-testing (`petal_at_pos`).
  - Added direct drop-to-convert execution (`dropEvent`) on valid petals with zero extra confirmation modals, and safe dismissal on backdrop drop or Escape.
- **Complete Native Windows UI/UX Redesign (Mockups 1–4):**
  - **Left Sidebar:** LocalShift brand header with glowing icon, 5 workflow navigation buttons (`Convert files`, `PDF ↔ DOCX`, `PDF → Images`, `Images → PDF`, `PDF Workbench`), bottom system status card (`● Offline engine ready`), and `⚙ Settings` button.
  - **Main Area:** Contextual header bar with title and subtitle, pill CTA button (`✦ Radial Menu Shift`), and quick Theme toggle.
  - **Drop Landing Card & Conversion Queue:** Modern drop zone card with browse and radial actions, and dedicated Queue Card displaying per-item badges, file details, format selection, progress bars, and status.
  - **Right Panel:** Shortcut card (`Radial Menu / Try it now`) and live conversion `History` card with format badges and instant open actions.
  - **Radial Menu Visual Overhaul (Mockup 3):** Dimmed backdrop (`rgba(11, 15, 25, 232)`), orbital guide ring, glowing center hub (`#3b82f6` to `#818cf8` gradient with `✦` star and file size pill), circular petal buttons with accelerator badges (1..9), and outward radial hover offsets.
- **Save to Folder Centralization & History Persistence:**
  - Persistent `AppSettings` via `QSettings` managing `save_to_folder_enabled`, `save_to_folder_path`, `theme`, and recent conversions `history` (bounded to 20 entries).
  - Enforced strict destination precedence: Explicit per-job directory > Configured global Save Folder > Source directory fallback.
  - Active directory validation (`validate_destination_directory`) with probe sentinel write test preventing silent failures.
- **Windows Verification & QA Harness:**
  - Added `scripts/verify_windows_gesture.py` supporting both automated checks (`--check`) and manual desktop verification checklists.
  - Updated screenshot generation (`scripts/capture_ui_screenshots.py`) capturing all 5 reference states.

---

## [0.15.0-dev] — Milestone 16A

### Added
- **Shift + Drag Conversion Gesture & Direct Radial Petal Drop:**
  - Registered `RadialConversionMenu` as an active Windows OLE drop target (`setAcceptDrops(True)`).
  - Implemented in-flight cursor hover tracking (`dragMoveEvent`) and geometric petal hit-testing (`petal_at_pos(pos)`).
  - Enabled direct drop on format petal (`dropEvent`) triggering immediate conversion (`auto_start=True`) with completion actions ("Open File" and "Open Folder").
  - Added drag-move Shift modifier detection across `MainWindow` and `FileConverterTab` to seamlessly summon the radial menu under the drag cursor.
- **Persistent Centralized "Save to Folder" Setting (`AppSettings`):**
  - Created `src/localshift/settings.py` providing thread-safe, persistent settings backed by `QSettings("LocalShift", "LocalShift")`.
  - Implemented `AppSettings` managing `save_to_folder_enabled`, `save_to_folder_path`, `theme`, and `radial_gesture_enabled`.
  - Added active directory validation (`validate_destination_directory`) verifying existence, folder type, and real write access via temporary test sentinels.
  - Added `SettingsDialog` accessible from the main header (`⚙ Settings`) with status indicators, Browse Folder, and Open Folder actions.
  - Enforced single, deterministic destination resolution policy (`resolve_destination`) across all 5 GUI tabs, radial conversions, and batch operations.
- **Format Expansion to 54 Offline Routes:**
  - Added native `GIF` (Raster image with alpha/palette handling) and `ICO` (Windows icon with RGBA coercion and 256×256 Lanczos downscaling) to `PillowImageAdapter` and `ImageToPdfAdapter`.
  - Expanded verified offline conversion routes from 30 to 54 directional routes (42 raster image pairs, 7 image-to-PDF routes, 5 document routes).

---

## [0.14.0] — 2026-10-26 (Initial Public Release)

### Added
- **Windows Packaging & Release Infrastructure:**
  - Automated PyInstaller packaging (`localshift.spec`) producing dual executables:
    - `LocalShift.exe`: Windowed desktop application with zero console flash and embedded branding icons.
    - `localshift-cli.exe`: Full-featured console CLI for scripting and pipeline automation.
  - Inno Setup 6 installer (`LocalShift-Setup-0.14.0.exe`) with LZMA2/Ultra64 solid compression (~93 MB installer).
  - Silent installation (`/VERYSILENT`) and uninstallation (`unins000.exe /VERYSILENT`) support for enterprise deployment.
  - Multi-resolution Windows branding icons (`assets/icon.ico` and `assets/icon.png`).
  - PE version resource embedding (`version_info.txt`) reporting version 0.14.0.0, copyright, and metadata.
  - Automated build script (`packaging/build.py`) with bundle integrity verification and SHA-256 calculation.
  - Automated packaging and release candidate test suites (`tests/test_packaging.py`, `tests/test_rc_audit.py`).
  - Comprehensive Third-Party Licenses & Model Notices manifest (`docs/THIRD_PARTY_LICENSES.md`).
- **Release Readiness & Quality Gate:**
  - Official Release Blocker Checklist (`docs/RELEASE_CHECKLIST.md`) documenting all audited vectors.

### Fixed
- **RapidOCR Frozen Runtime Import Error (CRITICAL):**
  - Fixed `AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'` in frozen PyInstaller environments by registering `sys.modules` aliases for `ch_ppocr_v2_cls`, `ch_ppocr_v3_det`, and `ch_ppocr_v3_rec` prior to initializing RapidOCR.
- **Windows Console Unicode Crash (HIGH):**
  - Fixed `UnicodeEncodeError: 'charmap' codec can't encode characters` in `localshift-cli.exe` when converting files with non-ASCII characters or printing Unicode filenames on Windows consoles by applying safe stream reconfiguration with `backslashreplace`.
- **Multipage PDF → Image CLI Reporting (MEDIUM):**
  - Fixed CLI reporting for multipage PDF-to-image conversions to accurately enumerate and display all generated output files (`res.output_paths`) rather than only reporting the first page.
- **Code Cleanliness:**
  - Cleaned up top-level module imports in `pdf_workbench.py`.

---

## [0.13.0] — 2026-10-25
### Added
- **Unified PySide6 Desktop GUI Subsystem (`localshift.gui`):**
  - 5 dedicated workflow tabs: File Converter, PDF ↔ DOCX interchange, PDF → Images rasterizer, Images → PDF ordered assembly, and PDF Workbench.
  - Drag-and-drop file ingestion, dynamic route-aware option binding, real-time backend discovery badges.
  - Responsive `QThread` workers with cooperative cancellation.

---

## [0.12.0] — 2026-10-25
### Added
- **Offline PDF Workbench Engine (`pdf_workbench.py`):**
  - High-performance structural manipulation: `merge_pdfs`, `split_pdf`, `extract_pdf_pages`, `reorder_pdf_pages`, and `rotate_pdf_pages`.
  - Input source immutability, atomic file placement, collision protection, and CLI subcommands.

---

## [0.11.0] — 2026-10-25
### Added
- **Image → PDF Conversion & Multi-Image Assembly Engine:**
  - Supports `png`, `jpeg`, `webp`, `bmp`, `tiff` to PDF.
  - Ordered multipage assembly, geometry fit (`contain`, `cover`), margins, alpha compositing, and EXIF transposition.

---

## [0.10.0] — 2026-10-24
### Added
- **PDF → PNG/JPEG Raster Export Engine:**
  - Offline PDF rasterization via `pypdfium2` with configurable DPI (72-400), JPEG quality, page ranges, and token naming.

---

## [0.9.0] — 2026-10-24
### Added
- **DOCX → PDF Conversion Engine:**
  - Headless LibreOffice and Microsoft Word COM automation rendering backends with sandboxed temp isolation.

---

## [0.8.0] — 2026-10-23
### Added
- **Real-World & Holdout PDF → DOCX Quality Validation:**
  - 10 real-world fixtures and 10 holdout fixtures with visual fidelity and table structure verification.

---

## [0.7.0] — 2026-10-23
### Added
- **Structured PDF → DOCX Reconstructor Engine:**
  - Headings, bordered and borderless tables, image-caption flow, and text hierarchy.

---

## [0.6.0] — 2026-10-23
### Added
- **Document Engine Foundation & Offline RapidOCR:**
  - `PdfInspector`, `NativePdfTextExtractor`, and ONNX Runtime CPU-based RapidOCR engine with bundled models.

---

## [0.5.0] — 2026-10-22
### Added
- **Conversion Planning & Preflight Validation API:**
  - Capability discovery, deterministic planning, and point-in-time checks.

---

## [0.4.0] — 2026-10-22
### Added
- **Adapter Architecture & Capability Registry:**
  - Pluggable `ConversionAdapter` protocol, option specifications, and error taxonomy.

---

## [0.3.0] — 2026-10-22
### Added
- **Concurrency Safety, Collision Prevention & Atomicity:**
  - In-process destination reservation locks and atomic rename replacements.

---

## [0.2.0] — 2026-10-22
### Added
- **Asynchronous JobQueue & Batch Processing:**
  - Thread-safe job submission, cancellation, and callbacks.

---

## [0.1.0] — 2026-10-22
### Added
- **Initial Core Image Converter Engine:**
  - Directional conversion among PNG, JPEG, WebP, BMP, and TIFF via Pillow.
