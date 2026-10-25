# LocalShift v0.14.0 — Release Blocker & Quality Gate Checklist

**Target Version:** 0.14.0 (Final Release)  
**Audit Date:** October 26, 2026  
**Status:** **PASS** (Release Quality Gate Passed)  
**Evaluator:** Senior Release QA Engineer & Security Reviewer  

---

## 1. Executive Quality Gate Summary

| Category | Total Criteria | PASS | FAIL | NOT VERIFIED | Gate Decision |
|---|---|---|---|---|---|
| **Packaging & Binaries** | 6 | 6 | 0 | 0 | **PASS** |
| **Installation & Lifecycle** | 5 | 5 | 0 | 0 | **PASS** |
| **Functional Workflows (CLI & GUI)** | 8 | 8 | 0 | 0 | **PASS** |
| **OCR & Neural Inference** | 4 | 4 | 0 | 0 | **PASS** |
| **Resilience & Edge Cases** | 6 | 6 | 0 | 0 | **PASS** |
| **Security & Privacy** | 5 | 5 | 0 | 0 | **PASS** |
| **Enterprise & Multi-User** | 3 | 2 | 0 | 1 | **CONDITIONAL PASS** |
| **TOTAL** | **37** | **36** | **0** | **1** | **PROCEED TO FINAL RELEASE** |


---

## 2. Release Blockers Audited & Resolved

### Blocker 1: RapidOCR Module Resolution in Frozen Executable
- **Severity:** CRITICAL (Release Blocker)
- **Status:** **PASS (Resolved & Verified)**
- **Evidence:** Running `localshift-cli.exe convert doc_05_english_scan.pdf --to txt` resulted in:
  ```text
  AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'
  ```
- **Root Cause:** RapidOCR uses dynamic string imports (`importlib.import_module("ch_ppocr_v3_det")`) expecting top-level module names. In PyInstaller frozen bundles, these modules are packaged under `rapidocr_onnxruntime.ch_ppocr_v3_det`. The empty filesystem data folder caused Python to load a namespace package without attributes.
- **Fix:** In `src/localshift/documents/ocr.py`, dynamically registered `sys.modules` aliases (`ch_ppocr_v3_det`, `ch_ppocr_v3_rec`, `ch_ppocr_v2_cls`) prior to RapidOCR initialization. In `packaging/localshift.spec`, added submodules to `hidden_imports`.
- **Regression Test:** `tests/test_rc_audit.py::test_rapidocr_module_aliases`.
- **Verification Result:** Verified in `dist/LocalShift/localshift-cli.exe` and `dist/test_rc_install/localshift-cli.exe` extracting 140 characters of accurate text from `doc_05_english_scan.pdf`.

---

### Blocker 2: Windows Console Unicode Encode Crash
- **Severity:** HIGH (Release Blocker)
- **Status:** **PASS (Resolved & Verified)**
- **Evidence:** Converting files with non-ASCII or Emoji filenames (`тест 測試 📄 spaces.png`) crashed `localshift-cli.exe` with:
  ```text
  UnicodeEncodeError: 'charmap' codec can't encode characters in position 59-62: character maps to <undefined>
  ```
- **Root Cause:** Default Windows console code pages (such as CP1252 or CP437) cannot encode arbitrary Unicode characters when printing to `sys.stdout` or `sys.stderr`.
- **Fix:** Added safe stream reconfiguration (`reconfigure(errors="backslashreplace")`) to `src/localshift/cli.py` and `packaging/entrypoint_cli.py`.
- **Regression Test:** `tests/test_rc_audit.py::test_cli_unicode_and_spaces_handling`.
- **Verification Result:** Tested directly in `localshift-cli.exe`, returning exit code 0 and cleanly formatting paths with backslashreplace without crashing.

---

### Blocker 3: Incomplete Multi-Output CLI Reporting
- **Severity:** MEDIUM (Functional Bug)
- **Status:** **PASS (Resolved & Verified)**
- **Evidence:** Running `localshift convert multipage.pdf --to png` generated all pages on disk, but the CLI only printed `Saved: multipage_page_1.png`.
- **Root Cause:** `cli.py` called `convert_image()` which returned only a single `Path` (`res.output_path`), discarding `res.output_paths`.
- **Fix:** Updated `cli.py` to call `convert_request()` and iterate over `res.output_paths` when multiple files are created.
- **Regression Test:** `tests/test_rc_audit.py::test_cli_multipage_pdf_to_images`.
- **Verification Result:** Verified output displays `Saved:` for every generated page.

---

## 3. Comprehensive Verification Matrix

| # | Test Scenario | Mechanism | Result | Notes |
|---|---|---|---|---|
| 1 | GUI Cold Launch | Subprocess offscreen execution | **PASS** | `LocalShift.exe` launches cleanly without terminal window. |
| 2 | GUI Repeated Launch | Subprocess sequence | **PASS** | Zero resource lockups or zombie background processes. |
| 3 | CLI Basic Commands | `localshift-cli.exe --help`, `convert --help`, `pdf --help` | **PASS** | Help displayed immediately with exit code 0. |
| 4 | Image ↔ Image Conversion | PNG → JPEG with packaged CLI | **PASS** | Converted cleanly with exit code 0. |
| 5 | Image → PDF Conversion | PNG → PDF with packaged CLI | **PASS** | Valid PDF generated with exit code 0. |
| 6 | PDF → Images Rasterization | Multipage PDF → PNG with packaged CLI | **PASS** | All pages generated and reported. |
| 7 | PDF → DOCX Reconstruction | Sample PDF → DOCX with packaged CLI | **PASS** | Structured Word document generated with exit code 0. |
| 8 | DOCX → PDF Rendering | DOCX → PDF via Word COM automation | **PASS** | Live PDF document generated with exit code 0. |
| 9 | PDF Workbench: Merge | Merging multiple PDFs | **PASS** | Pages combined in order. |
| 10 | PDF Workbench: Rotate | Rotating pages by 90° | **PASS** | Rotated document generated with exit code 0. |
| 11 | PDF Workbench: Split | Splitting PDF to pages | **PASS** | Individual page files created and enumerated. |
| 12 | PDF Workbench: Reorder | Permuting page sequence | **PASS** | Correct page ordering applied. |
| 13 | OCR: Scanned PDF | `doc_05_english_scan.pdf` → TXT | **PASS** | 140 chars extracted with neural model inference. |
| 14 | OCR: Digital PDF | Native extraction fallback | **PASS** | Instant text extraction without invoking OCR. |
| 15 | OCR: Unsupported Script | Non-registered language | **PASS** | Returns clear diagnostic message without crashing. |
| 16 | Filenames with Spaces | `file with spaces.png` | **PASS** | Quoted and unquoted paths handled correctly. |
| 17 | Filenames with Unicode | Cyrillic, CJK, Emoji | **PASS** | No charmap encoding exceptions. |
| 18 | Long Paths (>260 chars) | Deep folder trees | **PASS** | Resolved via standard Python pathlib Windows prefixing. |
| 19 | Existing Output Collision | Target file already exists | **PASS** | Automatically adds ` (1)`, ` (2)` suffix; never overwrites. |
| 20 | Source Overwrite Guard | Target path same as source | **PASS** | Trapped and rejected via `DestinationConflictError`. |
| 21 | Corrupt Input File | Truncated/garbage PDF | **PASS** | Clean exit code 2: `Corrupt or invalid PDF file`. |
| 22 | Password-Protected PDF | Encrypted PDF (`doc_10`) | **PASS** | Trapped: `password-protected or encrypted`. |
| 23 | Oversized Input File | Input exceeding 250 MiB limit | **PASS** | Trapped: `InputTooLargeError`. |
| 24 | Empty PDF File | 0-page PDF (`doc_13`) | **PASS** | Trapped: `contains 0 pages`. |
| 25 | Cooperative Cancellation | User aborts conversion worker | **PASS** | Worker terminates, temp files unlinked, no orphaned locks. |
| 26 | Partial Output Cleanup | Conversion failure midway | **PASS** | Atomic temp files unlinked on failure. |
| 27 | Offline Execution | Disconnected network adapter | **PASS** | 100% local CPU processing, zero network calls. |
| 28 | Silent Installation | `/VERYSILENT /SUPPRESSMSGBOXES` | **PASS** | Installed without prompts or dialogs. |
| 29 | Per-User Installation | Standard non-admin directory | **PASS** | Installed cleanly to `%LOCALAPPDATA%\Programs`. |
| 30 | All-Users Installation | `C:\Program Files\LocalShift` | **PASS** | Admin UAC prompt displayed when elevation requested. |
| 31 | Silent Uninstallation | `unins000.exe /VERYSILENT` | **PASS** | Installed files removed completely; user outputs preserved. |
| 32 | Clean Reinstallation | Install -> Uninstall -> Reinstall | **PASS** | Zero leftover registry or lock conflicts. |
| 33 | Windows Defender | Local scan of installer and binaries | **PASS** | Zero malware or heuristic threats detected. |
| 34 | Portable Execution | Run from `dist/LocalShift/` directly | **PASS** | Zero installation footprint, identical functionality. |
| 35 | License Compliance | Third-party dependency audit | **PASS** | Zero GPL copyleft dependencies bundled; LGPL satisfied. |
| 36 | Full Regression Suite | Pytest test execution | **PASS** | 563 passed, 3 skipped, 0 failed. |
| 37 | Clean VM / Domain Account | Non-domain clean VM execution | **NOT VERIFIED** | Tested on primary Windows 11 host; VM environment was not available on this host. |

---

## 4. Known Limitations & Release Advisories

1. **SmartScreen / Authenticode Warning:**
   - *Status:* Expected for open-source unsigned binaries.
   - *Advisory:* Because the executable is not signed with a commercial EV Authenticode certificate ($300-500/yr), Windows SmartScreen will display an informational "Unknown Publisher" warning on initial download until reputation is established.
   - *Remedy:* Users can click "More Info" -> "Run anyway", or organizations can deploy via Group Policy / Intune using the verified SHA-256 hash.
2. **DOCX → PDF Optional Rendering Backend:**
   - *Status:* Operating as designed.
   - *Advisory:* DOCX to PDF conversion requires Microsoft Word or LibreOffice installed locally on the Windows host. If neither is installed, the UI displays an informative badge and the route is safely omitted from advertised capabilities without crashing.
3. **Symlinks on Windows:**
   - *Status:* Operating as designed.
   - *Advisory:* Creating filesystem symlinks on Windows requires administrative privileges or Windows Developer Mode enabled. The 3 skipped tests in the regression suite exercise developer-mode symlink creation.
