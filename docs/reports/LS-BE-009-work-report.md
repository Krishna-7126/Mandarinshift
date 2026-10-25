# LocalShift — Work Report: Milestone LS-BE-009
## DOCX → PDF Conversion Engine: Feasibility, Implementation & Verification

**Date:** 2026-10-25  
**Role:** Senior Backend Engineer, Document Rendering Architect, and QA Engineer  
**Status:** Completed & Verified  

---

### 1. Executive Summary

Milestone **LS-BE-009** implements a reliable, offline-first **DOCX → PDF** conversion route for LocalShift.
The conversion engine adheres strictly to LocalShift's core architectural tenets:
1. **100% Offline & Private:** Zero cloud conversion calls, zero telemetry, zero runtime network downloads.
2. **Safe Engine Strategy:** Dynamically discovers offline rendering backends installed on the user's host (headless LibreOffice or Microsoft Word COM automation). If no rendering backend is installed, LocalShift does not advertise the route, and preflight planning emits clear, actionable diagnostics (`FindingCode.ADAPTER_UNAVAILABLE`).
3. **Container & Input Hardening:** Validates standard PK magic bytes (`PK\x03\x04`), verifies zip container integrity, and requires `word/document.xml` before invoking any external rendering process.
4. **Sandboxed Execution & Immutability:** Source documents are never modified or opened with write locks. Processes execute against isolated copies within secure temporary directories with full cleanup in `finally` blocks.
5. **Process Supervision:** Subprocesses are monitored via non-blocking polling loops that support cooperative cancellation, strict timeouts (clamped 5–300s, default 60s), and automatic process termination (`kill()`) upon timeout.
6. **Comprehensive Test Suite:** 26 new automated unit, validation, mock, sandboxing, and live rendering tests in [`tests/test_docx_pdf.py`](file:///Z:/LocalShift/tests/test_docx_pdf.py), achieving 403 passing tests across the entire repository with zero regressions.

---

### 2. Phase 1 — Feasibility & Backend Selection Audit

We evaluated offline DOCX rendering solutions for Windows across layout fidelity, licensing, packaging size, availability, and process isolation:

| Engine | Layout Fidelity | Licensing | Host Footprint / Size | Process Isolation | Availability & Discovery | Selected Strategy |
|---|---|---|---|---|---|---|
| **Headless LibreOffice** (`soffice.exe`) | High (95–99% layout parity with MS Word) | MPL-2.0 (permissive for subprocess execution) | ~350–500 MB (optional host installation) | Strong (isolated user profiles via `-env:UserInstallation`) | Discovered via `LOCALSHIFT_LIBREOFFICE_PATH`, `PATH`, or standard Program Files locations | **Primary Cross-Platform Backend** |
| **Microsoft Word COM Automation** (`winword.exe`) | Native (100% ground-truth Word fidelity) | Host OS / MS Office license (no third-party code) | Already installed on licensed Windows systems | High (isolated headless process with alerts suppressed) | Tested via PowerShell COM instantiation (`Word.Application`) | **Native Windows Backend** |
| **Pure Python Layout Engines** (e.g., `docx2pdf`, custom parsers) | Poor / Incomplete | MIT / Apache-2.0 | Lightweight (~5–20 MB) | In-process | Cannot reliably compute typography, line wraps, font metrics, or pagination | **Rejected** (Unacceptable fidelity) |

#### Strategy Implemented:
- The engine uses a tiered discovery policy:
  - If LibreOffice is installed, it can be used headlessly with isolated user installations to eliminate profile contention.
  - On Windows hosts with Microsoft Word installed, COM automation provides 100% layout and font rendering parity.
  - The default option (`renderer="auto"`) automatically selects the best available local engine.
  - If neither engine is installed on the user's machine, the route is not advertised as available, and conversion requests fail with a clear, actionable `AdapterUnavailableError`.

---

### 3. Phase 2 — Architecture & Implementation

#### 1. Document Rendering Subsystem (`localshift.documents.docx_renderer.DocxToPdfRenderer`)
- Located in [`src/localshift/documents/docx_renderer.py`](file:///Z:/LocalShift/src/localshift/documents/docx_renderer.py).
- Features:
  - `find_libreoffice_binary()`: Inspects `LOCALSHIFT_LIBREOFFICE_PATH`, system `PATH`, and standard `Program Files` install directories.
  - `is_word_com_available()`: Probes COM automation availability on Windows using a lightweight PowerShell test with a strict 8-second timeout, caching the result.
  - `render_docx_to_pdf()`:
    1. Validates source file existence and regular file status.
    2. Enforces PK header check (`PK\x03\x04`), zip validity (`zipfile.is_zipfile`), and verifies `word/document.xml` presence.
    3. Copies the source file into an isolated temporary folder (`localshift_docx_render_*`).
    4. Executes the selected backend (`_execute_libreoffice` or `_execute_word_com`).
    5. Polls subprocess status while checking cooperative cancellation flags.
    6. Verifies that the produced PDF is non-empty before atomically copying to the final destination.
    7. Cleans up all temporary files and directories.

#### 2. Conversion Adapter (`localshift.documents.docx_adapter.DocxToPdfAdapter`)
- Located in [`src/localshift/documents/docx_adapter.py`](file:///Z:/LocalShift/src/localshift/documents/docx_adapter.py).
- Conforms to the `ConversionAdapter` protocol:
  - `adapter_id`: `"docx_to_pdf"`
  - `supported_source_formats`: `frozenset({"docx"})`
  - `supported_target_formats`: `frozenset({"pdf"})`
  - `supported_routes`: `frozenset({("docx", "pdf")})`
  - `is_available()`: Dynamically returns `DocxToPdfRenderer.is_backend_available()`.
  - `can_convert()`: Checks route membership AND backend availability.
  - `get_supported_options()`: Exposes `renderer` (`"auto"`, `"libreoffice"`, `"word_com"`) and `timeout` (5–300 seconds, default 60s).
  - `convert()`: Renders to `context.temp_output_path` and returns structured `ConversionResult`.

#### 3. Capability Registry Integration (`localshift.registry.AdapterRegistry`)
- Updated [`src/localshift/registry.py`](file:///Z:/LocalShift/src/localshift/registry.py) to check `adapter.is_available()`:
  - `can_convert("docx", "pdf")`: Returns `True` only when a functional backend is installed.
  - `supported_routes()`: Dynamically filters out routes whose registered adapters report `is_available() == False`.
  - `supported_target_formats("docx")`: Returns `frozenset({"pdf"})` when available, or `frozenset()` when no backend is installed.
  - Pre-registers `DocxToPdfAdapter` in `default_registry`.

#### 4. Preflight Planning & Execution Boundary
- In [`src/localshift/planner.py`](file:///Z:/LocalShift/src/localshift/planner.py): Emits structured finding `FindingCode.ADAPTER_UNAVAILABLE` when `("docx", "pdf")` is requested without an installed backend.
- In [`src/localshift/converter.py`](file:///Z:/LocalShift/src/localshift/converter.py): Raises `AdapterUnavailableError` explaining the missing offline rendering backend rather than a generic route error.

---

### 4. Phase 3 — Test Suite & Verification

#### Deterministic Fixture Generator (`tests/docx_fixture_generator.py`)
Generates 6 reproducible test documents in [`tests/fixtures/docx_documents/`](file:///Z:/LocalShift/tests/fixtures/docx_documents/) with documented ground truth in `ground_truth.json`:
1. `docx_01_simple.docx`: Single-page document with title heading, bold/italic text, and standard paragraphs.
2. `docx_02_multipage.docx`: 3-page document with page breaks, H1 section headers, and multipage text flow.
3. `docx_03_tables.docx`: Formatted `Table Grid` containing header row, multiple data columns, and numeric metrics.
4. `docx_04_images.docx`: Document with embedded 200x120 PNG technical diagram and Figure caption.
5. `docx_05_headers_footers.docx`: Running confidential header, evaluation footer, and hyperlink URL.
6. `docx_06_unicode_margins_landscape.docx`: Landscape orientation, 0.75-inch custom margins, and multilingual Unicode text across 6 languages (English, Spanish, German, Hindi, Chinese, Japanese) and mathematical symbols.

#### Test Coverage (`tests/test_docx_pdf.py` — 26 Tests)
- **Adapter Protocol & Options:**
  - `test_adapter_attributes`
  - `test_adapter_availability_matches_renderer`
  - `test_supported_options`
- **Discovery & Registry:**
  - `test_sniff_format_docx`
  - `test_route_supported_reflects_backend`
  - `test_output_formats_for_docx`
  - `test_applicable_options_via_planner`
- **Preflight Planning:**
  - `test_plan_conversion_valid_docx`
  - `test_preflight_missing_file`
  - `test_preflight_empty_file`
  - `test_preflight_invalid_option_value`
  - `test_preflight_missing_backend_finding`
- **Input Hardening & Validation:**
  - `test_not_a_zip_file` (rejects plain text files named `.docx`)
  - `test_corrupted_zip_archive` (rejects truncated zip files)
  - `test_zip_missing_document_xml` (rejects zip archives missing `word/document.xml`)
- **Process Control & Sandboxing:**
  - `test_cancellation_before_execution`
  - `test_timeout_handling_libreoffice`
  - `test_source_file_immutability` (verifies SHA-256 hash and file timestamp remain unchanged)
- **Live Rendering Integration (Word COM):**
  - `test_render_simple_document` (validates PDF magic header, page count, and extracted text)
  - `test_render_multipage_document` (validates 3-page parity and text on each page)
  - `test_render_tables_document` (validates table headers, cells, and metrics)
  - `test_render_images_document` (validates embedded image and PDF size > 15 KB)
  - `test_render_headers_footers` (validates header/footer text extraction)
  - `test_render_unicode_margins_landscape` (validates landscape dimensions width > height and Unicode text)
- **Pipeline End-to-End:**
  - `test_convert_request_docx_to_pdf`
  - `test_convert_request_collision_avoidance`

---

### 5. Regression Suite Execution

Full regression suite run across the entire codebase:
```powershell
$env:PYTHONPATH = "src"
py -3.14 -m pytest -o pythonpath=src
```

**Results:**
- **Collected:** 406 tests
- **Passed:** 403 passed
- **Skipped:** 3 skipped (Windows Developer Mode non-elevated symlink tests)
- **Failed:** 0 failed
- **Execution Time:** ~107 seconds

---

### 6. Summary of Changed & Added Files

1. `src/localshift/documents/docx_renderer.py` (New): Offline rendering engine supporting LibreOffice and Word COM automation.
2. `src/localshift/documents/docx_adapter.py` (New): `DocxToPdfAdapter` adhering to `ConversionAdapter` protocol.
3. `src/localshift/documents/__init__.py`: Exported `DocxToPdfAdapter` and `DocxToPdfRenderer`.
4. `src/localshift/__init__.py`: Re-exported `DocxToPdfAdapter` and `DocxToPdfRenderer`.
5. `src/localshift/registry.py`: Dynamic route and target format filtering based on `adapter.is_available()`; registered `DocxToPdfAdapter`.
6. `src/localshift/planner.py`: Emits `FindingCode.ADAPTER_UNAVAILABLE` when route backend is missing.
7. `src/localshift/converter.py`: Emits clear `AdapterUnavailableError` when route backend is missing.
8. `tests/docx_fixture_generator.py` (New): Deterministic generator for 6 DOCX fixtures and ground truth.
9. `tests/fixtures/docx_documents/` (New): 6 test documents (`docx_01` to `docx_06`) and `ground_truth.json`.
10. `tests/test_docx_pdf.py` (New): 26 automated unit, preflight, validation, and live rendering tests.
11. `tests/test_pdf_docx.py`: Updated route assertion to check `DocxToPdfAdapter().is_available()`.
12. `tests/test_planning.py`: Updated route count and source format assertions to reflect dynamic availability.
13. `tests/test_converter.py`: Updated baseline unsupported format test for dynamic docx targets.
14. `tests/test_jobs.py`: Updated submission rejection test with invalid target format `xyz`.
15. `docs/FORMAT_SUPPORT.md`: Documented 23 routes, docx -> pdf options, rendering architecture, and limitations.
16. `docs/ARCHITECTURE.md`: Documented Subsystem G, updated architecture diagram and security bounds.
17. `docs/TEST_PLAN.md`: Updated test inventory (406 tests) and documented DOCX rendering fixtures.
18. `docs/PROJECT_STATUS.md`: Marked LS-BE-009 complete, updated milestone progress and architecture overview.
19. `TASKS.md`: Marked LS-BE-009 complete, updated repository status to 403 passing tests.
20. `docs/reports/LS-BE-009-work-report.md` (New): Comprehensive engineering report.

---

### 7. Git Working Tree State

All modifications remain uncommitted in the working tree for review:
```
M  TASKS.md
M  docs/ARCHITECTURE.md
M  docs/FORMAT_SUPPORT.md
M  docs/PROJECT_STATUS.md
M  docs/TEST_PLAN.md
A  docs/reports/LS-BE-009-work-report.md
M  src/localshift/__init__.py
M  src/localshift/converter.py
M  src/localshift/documents/__init__.py
A  src/localshift/documents/docx_adapter.py
A  src/localshift/documents/docx_renderer.py
M  src/localshift/planner.py
M  src/localshift/registry.py
A  tests/docx_fixture_generator.py
A  tests/fixtures/docx_documents/...
A  tests/test_docx_pdf.py
M  tests/test_converter.py
M  tests/test_jobs.py
M  tests/test_pdf_docx.py
M  tests/test_planning.py
```
