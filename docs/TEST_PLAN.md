# LocalShift — Test Plan & Quality Assurance Strategy

**Version:** 0.16.2 (Updated: Milestone LS-BE-016D)  
**Test Suite Size:** 609 tests collected (606 passed, 3 skipped on non-admin Windows)  

---

## 1. Scope & Strategy

LocalShift uses a layered testing strategy focused strictly on backend correctness, safety, and reliability:
- **Unit Tests:** Fast, isolated testing of format normalization, magic-byte sniffing, options validation, and capability lookups.
- **Integration Tests:** End-to-end execution of `convert_request()` with real adapters, destination path collision resolution, atomic replacement, and cleanup verification.
- **PDF Color Fidelity & Pixel Accuracy Tests:** Automated visual color test suite asserting native RGB byte alignment, channel order verification (no Red/Blue swapping), pure primary color patch accuracy, Team Lemon yellow verification, alpha compositing against background, and Mean Absolute Error (MAE < 3.0) against reference specifications.
- **Radial Menu Stability & Hysteresis Tests:** Polar sector collision accuracy, sticky boundary hysteresis (±6° deadband), circular disc proximity, multi-monitor DPI boundary clamping, continuous cursor movement without jitter or oscillation, and non-focus-stealing window flags.
- **Windows Shell & Background Gesture Tests:** Active Explorer selection retrieval via `IShellWindows`, foreground window validation, "Start with Windows" registry key configuration, non-invasive drag tracking, source-adapter architecture (Explorer, Desktop, OLE, Fallback), discrete state machine transitions (`GestureState`), instant Escape cancellation, and system tray integration.
- **XML 1.0 Compatibility & Reconstruction Tests:** Centralized sanitization of illegal ASCII control chars (`0x00–0x08`, `0x0E–0x1F`), conversion of vertical tabs and form feeds, Unicode emoji and multi-lingual preservation, atomic temporary replacement.
- **Reliability & Concurrency Tests:** In-process path reservation locks, thread-safe job queue lifecycle, worker pool thread exhaustion, and cancel propagation.
- **Document & OCR Tests:** Offline OCR engine invocation, bounding box parsing, line grouping, memory-bounded rendering, DPI bounds, per-page routing (`auto`, `native_only`, `force_ocr`), text de-duplication, memory ownership, language model audits, CJK punctuation normalization, faint scan preprocessing, 180° upside-down and 90°/270° orientation recovery, and offline language pack registration.
- **Benchmark Corpus Quality Tests:** Deterministic evaluation of text extraction accuracy (Character Error Rate, Word Error Rate, Unicode preservation, reading order, and heap memory tracing) in both native and auto OCR modes across 18 benchmark categories.
- **Unseen Document Generalization Tests:** Independent validation against 10 unseen fixtures (`val_01` to `val_10`) never used for tuning, testing generalization on contracts, ledgers, receipts, multilingual text, and multi-page manuscripts.
- **Real-World Document Evaluation Tests:** Comprehensive validation across 10 diverse real-world documents (`rw_01` to `rw_10`) evaluating born-digital specifications, corporate balance sheets, multi-column research papers, thermal scan receipts, mixed digital/scanned contracts, multilingual trade treaties, mixed-orientation reports, hardware manuals with figures, 6-page statutory acts, and employment application forms.
- **Independent Holdout Corpus & Quality Gate:** Rigorous validation against 10 separate untouched holdout fixtures (`holdout_01` to `holdout_10`) evaluating earnings reports, clinical trials, upside-down scans, mixed records, patent claims, 10-page bylaws, and corrupt edge-case handling against strict release thresholds.
- **DOCX → PDF Offline Document Rendering Tests:** Dedicated test suite validating adapter protocol, capability advertising, strict container integrity, missing backend handling, subprocess timeout and cancellation, source document immutability, and live rendering across simple, multipage, tabular, media, headers/footers, and landscape multilingual fixtures.
- **PDF → PNG/JPEG Raster Export Engine Tests:** Dedicated test suite validating page selection syntax (all, single, ranges, lists, bounds), option validation (DPI, JPEG quality, patterns, background), single-page and multipage export, atomic placement, collision protection, cooperative cancellation, and corrupted/encrypted/empty PDF handling.
- **Image → PDF Assembly & Conversion Tests:** Dedicated test suite validating single image to PDF, multiple image ordered multipage assembly, batch conversion, page size handling (`original`, `a4`, `letter`), fitting modes (`contain`, `cover` center crop), orientation (`portrait`, `landscape`, `auto`), margins, background color fill with transparency compositing, non-RGB mode conversions (CMYK, Grayscale, Paletted), EXIF orientation tags, pixel ceilings, collision avoidance, and cleanup on failure.
- **PDF Workbench Subsystem Tests:** Dedicated test suite validating multi-document merge ordering and page dimension preservation, split subset exports, custom naming patterns with token substitution, single-document page extraction, page reordering via 1-based index sequences, rotation angles (90°, 180°, 270°, negative angles, relative vs absolute), input source immutability, collision avoidance, cancellation cleanup, and CLI subcommands.
- **Desktop GUI Integration & Workflow Tests:** Automated offscreen PySide6 tests validating window initialization, 5 dedicated workflow tabs, drag-and-drop file queue additions, queue reordering (move up/down, remove, clear), format resolution, option validation, backend discovery status, background `QThread` workers with cooperative cancellation, and real end-to-end execution of conversions through the GUI layer.
- **Windows Packaging & Release Tests:** Automated tests validating PyInstaller build specifications, dual GUI/CLI targets, resource bundling (`rapidocr_onnxruntime` models, `pdfium.dll`, `onnxruntime.dll`), exclusion of heavy scientific/development packages, PE version resource metadata, multi-resolution application icons, and Inno Setup installer script syntax.
- **Release Candidate QA & Stability Audit Tests:** Automated tests validating stream encoding safety on Windows consoles, multi-output CLI reporting, RapidOCR module aliasing in frozen environments, and corrupt/encrypted edge-case handling.

---

## 2. Test File Inventory

| Test Module | Test Focus | Count | Key Assertions |
|---|---|---|---|
| [`tests/test_converter.py`](file:///Z:/LocalShift/tests/test_converter.py) | Core converter engine & legacy API | 63 | All image routes, collisions, alpha composite, atomic write |
| [`tests/test_adapters.py`](file:///Z:/LocalShift/tests/test_adapters.py) | Adapter contract & protocol checks | 31 | `ConversionAdapter` protocol, option specs, conflict detection |
| [`tests/test_jobs.py`](file:///Z:/LocalShift/tests/test_jobs.py) | Asynchronous JobQueue & batching | 80 | Lifecycle states, queue limits, eviction, thread safety |
| [`tests/test_planning.py`](file:///Z:/LocalShift/tests/test_planning.py) | Planning API & preflight validation | 30 | Capability discovery, `ConversionPlan`, point-in-time checks |
| [`tests/test_reliability.py`](file:///Z:/LocalShift/tests/test_reliability.py) | Concurrency & resource stress | 51 | Collision races, symlink safety, cancellation, memory safety |
| [`tests/test_document_foundation.py`](file:///Z:/LocalShift/tests/test_document_foundation.py) | Document container sniffing & fixtures | 5 | PDF `%PDF-` sniffing, DOCX OpenXML structure, 18 fixture generation |
| [`tests/test_pdf_extraction.py`](file:///Z:/LocalShift/tests/test_pdf_extraction.py) | PDF inspection & text extraction | 34 | Page counts, dimensions, rotations, text previews, adapter, `ocr_language` |
| [`tests/test_pdf_reliability.py`](file:///Z:/LocalShift/tests/test_pdf_reliability.py) | Benchmark quality & metrics | 18 | CER / WER calculations, benchmark corpus verification, latency |
| [`tests/test_pdf_ocr.py`](file:///Z:/LocalShift/tests/test_pdf_ocr.py) | Offline OCR engine, renderer & routing | 31 | RapidOCR detection, reading order, scanned PDF extraction, DPI bounds, de-duplication, memory safety, language audit, CJK normalization, faint preprocessing, 180° upside-down and 90°/270° orientation recovery, language pack registration |
| [`tests/test_pdf_docx.py`](file:///Z:/LocalShift/tests/test_pdf_docx.py) | PDF to DOCX document reconstruction | 27 | Born-digital, scanned, mixed, tables, headings, lists, orientation, Unicode, image-caption flow, visual rendering QA |
| [`tests/test_unseen_validation.py`](file:///Z:/LocalShift/tests/test_unseen_validation.py) | Unseen document validation set | 7 | Generalization on legal contracts, financial ledgers, academic papers, multilingual text, manuscripts |
| [`tests/test_docx_pdf.py`](file:///Z:/LocalShift/tests/test_docx_pdf.py) | DOCX to PDF conversion engine | 26 | Adapter protocol, discovery, strict PK/XML validation, missing backend handling, timeout termination, cancellation, source immutability, Word COM live rendering |
| [`tests/test_pdf_image_export.py`](file:///Z:/LocalShift/tests/test_pdf_image_export.py) | PDF to PNG/JPEG raster export engine | 39 | Routes, page selection parser, DPI/quality validation, multipage export, custom pattern tokens, atomic placement, collision avoidance, cancellation, corruption handling |
| [`tests/test_image_to_pdf.py`](file:///Z:/LocalShift/tests/test_image_to_pdf.py) | Image to PDF conversion & assembly | 39 | All raster formats, multi-image assembly, page sizes, fit (contain/cover), orientation, margins, alpha background, CMYK/greyscale, EXIF, cancellation, cleanup |
| [`tests/test_pdf_workbench.py`](file:///Z:/LocalShift/tests/test_pdf_workbench.py) | PDF Workbench (Merge, Split, Extract, Reorder, Rotate) | 41 | Multi-PDF merge order & dimension preservation, split subset exports & pattern tokens, page extraction, 1-based index reorder, relative/absolute rotations (90/180/270/-90), immutability, collision avoidance, CLI commands |
| [`tests/test_gui.py`](file:///Z:/LocalShift/tests/test_gui.py) | PySide6 Desktop GUI integration & workflows | 30 | Tabs, queue loading, reorder, options binding, worker execution, cancellation, error dialogs |
| [`tests/test_radial_menu.py`](file:///Z:/LocalShift/tests/test_radial_menu.py) | Shift-activated Radial Conversion Menu & OLE gesture | 20 | Target derivation, multi-file intersection, keyboard nav, hit-testing, overlay mode, drag tracking, escape cancel, boundary hysteresis, fast sweep |
| [`tests/test_shell_integration.py`](file:///Z:/LocalShift/tests/test_shell_integration.py) | Windows Shell integration & GestureStateMachine | 8 | IShellWindows selection, autostart registry, DragSourceAdapter hierarchy, state machine transitions, Escape cancellation, non-activating window flags |
| [`tests/test_pdf_color_fidelity.py`](file:///Z:/LocalShift/tests/test_pdf_color_fidelity.py) | PDF color rendering fidelity & channel accuracy | 6 | Pure RGB primaries, Team Lemon yellow, neutral grays, PNG/JPEG/WebP/TIFF exports, MAE < 3.0 |
| [`tests/test_settings.py`](file:///Z:/LocalShift/tests/test_settings.py) | Persistent AppSettings, Save to Folder & resolution | 7 | QSettings persistence, directory validation probe, 3-tier precedence hierarchy |
| [`tests/test_packaging.py`](file:///Z:/LocalShift/tests/test_packaging.py) | Windows packaging, assets, version & installer | 6 | Spec configuration, dual targets, icon assets, version metadata, Inno Setup config |
| [`tests/test_rc_audit.py`](file:///Z:/LocalShift/tests/test_rc_audit.py) | Release Candidate QA & stability audit | 5 | Unicode console stream safety, multi-page CLI reporting, RapidOCR aliasing, corrupt input trap |



---

## 3. Benchmark Evaluation Harness (`tests/pdf_quality_evaluator.py`)

### Metrics Defined:
1. **Character Error Rate (CER):**
   $$\text{CER} = \frac{\text{Levenshtein}(\text{ref\_chars}, \text{hyp\_chars})}{\text{len}(\text{ref\_chars})}$$
2. **Word Error Rate (WER):**
   $$\text{WER} = \frac{\text{Levenshtein}(\text{ref\_words}, \text{hyp\_words})}{\text{len}(\text{ref\_words})}$$
3. **Strict vs. Normalized Scoring:**
   - **Normalized:** Standardizes whitespace runs (`\r\n`, `\t`, multiple spaces) to a single space. Preserves all punctuation, numbers, symbols, and diacritics.
   - **Strict:** Direct comparison without whitespace normalization.
4. **Memory Tracing:** Uses Python `tracemalloc` to track peak heap allocation delta during extraction.
5. **Execution Latency:** Uses `time.perf_counter()` to record extraction time in milliseconds.

### Reproduction Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 tests/pdf_quality_evaluator.py
```

---

## 4. Real-World Evaluation Harness (`tests/real_world_quality_evaluator.py`)

The real-world evaluation harness (`tests/real_world_generator.py` and `tests/real_world_quality_evaluator.py`) evaluates the conversion engine across 10 legally unencumbered real-world document categories:
1. `rw_01_technical_specification.pdf` (3 pages, hierarchical headings H1–H3, numbered clauses, bullet lists).
2. `rw_02_corporate_balance_sheet.pdf` (Financial schedule with parenthesized negative values e.g. `($1,250.00)` and dynamic column alignment).
3. `rw_03_research_paper_multicolumn.pdf` (Multi-column academic layout with abstract, Section headers, and references).
4. `rw_04_degraded_freight_receipt.pdf` (Thermal bill of lading scan with high background noise and faint text).
5. `rw_05_contract_with_notary_stamp.pdf` (3 pages: 2 digital contract pages with Article headings + 1 scanned notary seal page).
6. `rw_06_multilingual_trade_treaty.pdf` (Multilingual treaty text across English, German, French, and Spanish).
7. `rw_07_mixed_orientation_report.pdf` (3 pages: portrait, landscape `/Rotate 90`, and portrait).
8. `rw_08_hardware_manual_with_figures.pdf` (Technical equipment manual with embedded schematic diagram and Figure caption).
9. `rw_09_dense_regulatory_act.pdf` (Dense 6-page statutory act with semicolon-separated statutory clauses and numbered statutory items).
10. `rw_10_employment_application_form.pdf` (Grid-style tabular application form).

### Reproduction Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 tests/real_world_quality_evaluator.py
```

---

## 5. Independent Holdout Corpus & Quality Gate Matrix (`tests/holdout_quality_evaluator.py`)

The independent holdout evaluation harness (`tests/holdout_generator.py` and `tests/holdout_quality_evaluator.py`) enforces rigorous quality gates across 10 untouched holdout fixtures never used for engine tuning:
1. `holdout_01_quarterly_earnings_report.pdf` (4 pages: executive summary, income statement with negative accounting values, segment breakdown, forward-looking statements).
2. `holdout_02_clinical_trial_protocol.pdf` (3 pages: clinical trial protocol with section hierarchy, multi-arm dosing table, inclusion/exclusion lists).
3. `holdout_03_upside_down_scanned_invoice.pdf` (1 page: 180° upside-down scanned courier invoice to test automated raster inversion and reading order).
4. `holdout_04_mixed_patient_record.pdf` (4 pages: digital intake record, degraded thermal lab report, blank divider page, and scanned authorization seal).
5. `holdout_05_multilingual_patent_claim.pdf` (2 pages: international patent claims in English, German with umlauts, and French with accents).
6. `holdout_06_landscape_engineering_drawing.pdf` (1 page: 90° landscape orientation with component tolerances table).
7. `holdout_07_industrial_equipment_manual.pdf` (3 pages: equipment maintenance manual with embedded diagram and Figure caption).
8. `holdout_08_large_statutory_bylaws.pdf` (10 pages: multi-page legislative bylaws evaluating streaming latency and memory scaling).
9. `holdout_09_corrupt_or_truncated_edgecase.pdf` (1 page: intentionally damaged/truncated stream evaluating safe error trapping).
10. `holdout_10_procurement_purchase_order.pdf` (2 pages: itemized enterprise purchase order with line items and delivery terms).

### Reproduction Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 tests/holdout_quality_evaluator.py
```

---

## 6. Windows-Specific Testing Notes

1. **Path Normalization:** Windows paths are case-insensitive. All in-process reservations in `reserve_output_path()` normalize paths to lowercase canonical forms.
2. **File Locking:** Windows holds strict OS locks on open files (`PermissionError: [WinError 32]`). All file handles (Pillow images, PDFium documents, temporary files) must be closed in `finally` blocks before replacement or removal.
3. **Symlink Privileges:** Windows symlink creation requires Developer Mode or elevated privileges. Tests that create symlinks automatically check permissions and skip gracefully when running in standard non-elevated user mode.
4. **Word COM DisplayAlerts:** Microsoft Word COM automation sets `word.DisplayAlerts = 0` (wdAlertsNone) to suppress interactive modal dialogs during automated headless visual QA rendering.

---

## 7. DOCX → PDF Rendering Verification & Fixture Ground Truth (`tests/docx_fixture_generator.py`)

A deterministic test suite and fixture generator creates 6 dedicated DOCX test documents with ground truth metadata:
1. `docx_01_simple.docx` (1 page: title heading, bold/italic runs, standard paragraphs).
2. `docx_02_multipage.docx` (3 pages: page breaks, hierarchical H1 headings, technical breakdown paragraphs).
3. `docx_03_tables.docx` (1 page: `Table Grid` with header row, multi-column metrics, numeric data).
4. `docx_04_images.docx` (1 page: embedded 200x120 PNG technical diagram with Figure caption).
5. `docx_05_headers_footers.docx` (1 page: running header, page footer, hyperlink reference).
6. `docx_06_unicode_margins_landscape.docx` (1 page: landscape orientation, 0.75-inch custom margins, multilingual Unicode across English, Spanish, German, Hindi, Chinese, Japanese, and mathematical symbols).

### Reproduction Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 -m pytest -o pythonpath=src tests/test_docx_pdf.py
```

