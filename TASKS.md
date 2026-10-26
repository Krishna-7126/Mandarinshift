# LocalShift — Engineering Task Tracker

## Completed Milestones

- [x] **LS-BE-001**: Core Image Converter Engine (Pillow, formats, options, EXIF).
- [x] **LS-BE-002**: Asynchronous JobQueue & Batch Processing (threading, callbacks, limits).
- [x] **LS-BE-003**: Reliability & Security Hardening (collision reservations, atomic replacements, directory isolation).
- [x] **LS-BE-004**: Modular Adapter Architecture (registry, capabilities, error taxonomy).
- [x] **LS-BE-005**: Conversion Planning & Preflight Validation API (deterministic plans, point-in-time checks).
- [x] **LS-BE-006A**: Document Engine Foundation & Dependency Verification (format sniffing, dependency licensing).
- [x] **LS-BE-006B**: PDF Inspection & Native Text Extraction (`PdfInspector`, `NativePdfTextExtractor`, PDF → TXT).
- [x] **LS-BE-006C**: PDF Quality Verification & 14-Fixture Benchmark Corpus (CER/WER evaluation, Unicode, reading order).
- [x] **LS-BE-006D**: Offline OCR Engine Foundation & Scanned PDF Extraction (`RapidOcrEngine`, ONNX Runtime CPU, bounded rendering, per-page routing).
- [x] **LS-BE-006E**: Hybrid PDF Extraction Reliability, OCR Accuracy & Compatibility Audit (de-duplication, memory ownership, language audit, 335 tests passing).
- [x] **LS-BE-007A**: PDF → DOCX Conversion Engine: Architecture, Implementation & Verification (`PdfToDocxReconstructor`, headings, tables, paragraphs, images, 18 new tests, 354 tests passing).
- [x] **LS-BE-007B**: PDF → DOCX Quality Verification, Visual Fidelity & Real-World Benchmarking (`DocxVisualRenderer` via Word COM, borderless tables, image-caption flow, 18-fixture benchmark, 23 PDF-to-DOCX tests, 359 tests passing).
- [x] **LS-BE-007C**: PDF → DOCX Unseen-Document Validation & Reliability Audit (10 unseen validation fixtures, thousands-comma accounting table fix, Word COM DisplayAlerts hardening, 7 new tests, 366 tests passing).
- [x] **LS-BE-007D**: OCR Quality Engineering, Language Support & Scanned PDF Reliability (CJK full-width normalization, faint preprocessing, 90°/270° orientation recovery, LanguagePackConfig, unsupported language diagnostics, 6 new tests, 372 tests passing).
- [x] **LS-BE-008A**: Real-World PDF → DOCX Reliability & Quality Validation (10 real-world evaluation fixtures `rw_01` to `rw_10`, financial table parenthesized negative number matching, leading column alignment, Article heading detection, semicolon/numbered list boundaries, 4 new regression tests, 376 tests passing).
- [x] **LS-BE-008B**: Independent Holdout Validation & Conversion Quality Gate (10 untouched holdout fixtures `holdout_01` to `holdout_10`, 180° upside-down scan automatic orientation recovery, document-order stream evaluation, category-specific quality gate release criteria, 1 new regression test, 377 tests passing).
- [x] **LS-BE-009**: DOCX → PDF Conversion Engine: Feasibility, Implementation & Verification (`DocxToPdfRenderer`, `DocxToPdfAdapter`, dynamic availability, LibreOffice/Word COM backend discovery, isolated temp sandboxing, timeout kill, cooperative cancellation, 6 fixtures, 26 new tests, 403 tests passing).
- [x] **LS-BE-010**: PDF → PNG/JPEG Conversion Engine, Batch Export & Verification (offline rasterization engine via `PdfToImageExporter`, routes `pdf -> png` and `pdf -> jpeg`, single and multipage export, configurable DPI 72-400, JPEG quality 1-100, page selection parser, custom naming patterns with token substitution, per-page atomic placement and collision protection, multi-output `output_paths` in ConversionResult, cooperative cancellation and cleanup, 39 new tests, 442 tests passing).
- [x] **LS-BE-011**: Image → PDF Conversion Engine, Multi-Image Assembly & Verification (offline image-to-PDF conversion engine via `ImageToPdfConverter` and `ImageToPdfAdapter`, routes `png|jpeg|webp|bmp|tiff -> pdf`, single image to PDF, ordered multipage assembly, batch conversion, validated options for page size `original|a4|letter`, fit `contain|cover`, orientation `portrait|landscape|auto`, point margins, background color fill with transparency compositing, non-RGB conversions, EXIF auto-transposition, pixel ceilings, collision avoidance, atomic placement, 39 new tests, 481 tests passing).
- [x] **LS-BE-012**: PDF Workbench Engine: Merge, Split, Reorder & Rotate (offline structural PDF workbench via `PdfWorkbench`, operations `merge_pdfs`, `split_pdf`, `extract_pdf_pages`, `reorder_pdf_pages`, `rotate_pdf_pages`, multi-document merge ordering and dimension preservation, single-page and subset splits with custom pattern tokens, 1-based index page reordering, relative and absolute rotations for 90°/180°/270°/-90°, source input immutability, safe volume-local temp files, collision avoidance, cooperative cancellation, CLI subcommands `localshift pdf merge|split|extract|reorder|rotate`, 41 new tests, 522 tests passing).
- [x] **LS-BE-013**: Unified PySide6 GUI Integration & PDF Workbench UX (clean, minimal PySide6 desktop interface integrating 5 dedicated workflows: General File Converter, PDF ↔ DOCX interchange with live backend discovery, PDF → PNG/JPEG rasterizer with DPI/quality/page selection, Images → PDF ordered multi-image assembly, and PDF Workbench Merge/Split/Extract/Reorder/Rotate; drag-and-drop queue, output directory selection, options binding, responsive `QThread` workers with cooperative cancellation, 30 new tests, 552 tests passing).
- [x] **LS-BE-014**: Windows Packaging, Installer & Release Readiness (reproducible PyInstaller packaging producing `LocalShift.exe` GUI and `localshift-cli.exe` console binary, bundled OCR models, `pdfium.dll`, `onnxruntime.dll`, multi-resolution icons, Inno Setup 6 installer `LocalShift-Setup-0.14.0.exe` with silent install and clean uninstall, Defender/SmartScreen guidance, 6 new packaging tests, 558 tests passing).
- [x] **LS-BE-015**: Release Candidate QA, Installation Reliability & Stability Audit (audit of v0.14.0-RC1, resolved RapidOCR dynamic module loading in frozen PyInstaller bundles, fixed Windows console Unicode charmap encode crash, resolved multipage CLI reporting, 5 new RC audit tests, verified installer lifecycle, 563 tests passing).
- [x] **LS-BE-016**: Final Release & GitHub Publication Readiness (verified 37-point release gate, prepared third-party licenses manifest, generated portable zip bundle, synchronized version metadata, created GitHub release notes, release manifest, and publication commands).
- [x] **LS-BE-016A**: Shift+Drag Conversion Workflow, Format Expansion to 54 routes, and Global Save Destination setting.
- [x] **LS-BE-016B**: Reliable Shift+Drag Conversion & Premium UI/UX Rebuild (fixed OLE drag capture with In-Window Overlay architecture, Win32 GetAsyncKeyState Shift detection, complete visual redesign matching mockups 1–4 with sidebar navigation, right panel shortcut/history cards, 588 passed, 3 skipped, 0 failed).
- [x] **LS-BE-016C**: True Background Shift+Drag, Reliable PDF→DOCX, Conversion Performance & Premium UI Stabilization (fixed XML 1.0 illegal characters crash via `sanitize_xml_text()`, added `BackgroundGestureController` with physical mouse/Shift polling and Explorer selection extraction via `IShellWindows`, system tray integration, "Start with Windows" HKCU Run key, performance benchmarks across all routes, 597 passed, 3 skipped, 0 failed).
- [x] **LS-BE-016D**: Global Shift+Drag Stability, Smooth Radial Menu & Color-Accurate PDF Rendering (fixed PDFium BGR/RGB color inversion via `rev_byteorder=True` and `render_page_to_image()`; eliminated radial menu jitter and focus stealing via `WA_ShowWithoutActivating`, `WindowDoesNotAcceptFocus`, discrete `GestureStateMachine`, sticky boundary hysteresis ±6°, and `DragSourceAdapter` architecture; 606 passed, 3 skipped, 0 failed).
- [x] **LS-BE-017**: Comprehensive PDF Productivity Suite Architecture & UI Implementation (registry of all 32 PDF productivity tools with availability and options schema; native offline PDF tools engine covering page deletion, cropping, compression, unlocking, repair, Markdown conversion, page numbering, watermark, comparison, and forms inspection; searchable 3-column responsive tool grid UI with category pills, status badges, and interactive tool execution dialog; integrated into MainWindow navigation as 6th tab with workflow routing; 620 passed, 3 skipped, 0 failed).
- [x] **LS-BE-018**: Production Reliability, Conversion Quality & Performance (Exhaustive 54-route test suite in test_all_conversion_routes.py; verified structural integrity and source immutability; offline HTML to PDF and OCR PDF tools; accurate tool availability audit; expanded benchmarks across all workflows and tools; 678 passed, 3 skipped, 0 failed).
- [x] **LS-BE-019**: Complete PDF Suite, Functional Features & Production-Ready Offline Conversion (Functional implementations for all 32 advertised PDF tools: PDF to Excel, PDF to PowerPoint, PDF to PDF/A, Excel to PDF, PowerPoint to PDF, Sign PDF, Edit PDF, Redact PDF, Form filling, and Offline AI Summarizer; standardized READY/CONFIG_REQUIRED/PLANNED/UNSUPPORTED availability framework; dynamic dialog option editors; 25 passing PDF suite tests; 687 passed, 3 skipped, 0 failed across entire regression suite).

---

## Current Status

- **Version:** 0.19.0 (Milestone 19).
- **Test Suite:** 681 collected, 678 passed, 3 skipped, 0 failed (100% passing).
- **Python Version:** 3.14.3 on Windows 11 AMD64.
- **Packaging:** PyInstaller onedir distribution with dual GUI (`LocalShift.exe`) and CLI (`localshift-cli.exe`) targets.
- **Installer:** Inno Setup 6 compiled installer `dist/installer/LocalShift-Setup-0.14.0.exe` (93.34 MB, LZMA2/ultra64 compressed).
- **Portable Bundle:** `dist/LocalShift-v0.14.0-windows-x64.zip` (146.26 MB, SHA-256: `de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2`).
- **GUI Framework:** PySide6 v6.12.0 (LGPL-3.0) with zero backend dependency linkage.
- **DOCX Engine:** `python-docx` v1.2.0 (MIT) + `lxml` v6.1.3 (BSD-3).
- **OCR Engine:** RapidOCR v1.2.3 with ONNX Runtime v1.26.0 (CPUExecutionProvider).
- **Rendering Backends:** LibreOffice headless (`soffice.exe`) and Microsoft Word COM automation (`winword.exe`).
- **Language Support:** Bundled Latin + Simplified Chinese; clean offline `LanguagePackConfig` registration interface for Hindi/Devanagari and non-Latin scripts.
- **Visual QA Harness:** Microsoft Word COM automation rendering DOCX to PDF/images with 100% visual QA pass across 54 fixtures (18 synthetic + 10 unseen + 10 real-world + 10 holdout + 6 DOCX-to-PDF).
- **PDF Image Export:** Fully offline raster export to PNG/JPEG with page subset selection, custom naming tokens, atomic placement, and collision protection.
- **Image → PDF Engine:** Fully offline single and ordered multipage assembly from raster images with configurable geometry, margins, background compositing, and orientation.
- **PDF Workbench Engine:** High-performance offline PDF merge, split, extract, reorder, and rotate engine with source immutability, atomic placement, and full CLI integration.
- **Desktop Application:** Unified PySide6 desktop application with 5 dedicated workflow tabs and responsive worker threads.
- **Offline Guarantee:** 100% offline, local CPU processing. Zero network telemetry.

---

## Future Roadmap (Post v0.14.0)

- [ ] **LS-FEAT-001**: Office Document Text Extraction & Batch DOCX Ingestion (`docx` -> `txt`).
- [ ] **LS-FEAT-002**: Automatic Telemetry-Free GitHub Release Update Checking.



