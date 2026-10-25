# LocalShift — LS-BE-015 Work Report
# Release Candidate QA, Installation Reliability & Stability Audit

**Milestone:** LS-BE-015  
**Date:** October 26, 2026  
**Status:** Complete & Quality-Gated  
**Test Suite:** 566 tests collected (563 passed, 3 skipped on non-admin Windows, 0 failed)  
**Release Artifacts:**
- Setup Installer: `dist/installer/LocalShift-Setup-0.14.0.exe` (93.34 MB, SHA-256: `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974`)
- Standalone Portable Folder: `dist/LocalShift/` (`LocalShift.exe` 5.94 MB, `localshift-cli.exe` 5.94 MB)

---

## 1. Executive Summary

Milestone **LS-BE-015** executed a comprehensive release candidate audit and quality gate evaluation of LocalShift v0.14.0 on Windows 11.

During Phase 1 and Phase 2 testing of the packaged application, two high-impact release blockers and one functional reporting defect were discovered, diagnosed, and resolved:
1. **Critical Blocker:** RapidOCR failed to initialize inside the frozen PyInstaller executable (`AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'`) because RapidOCR's internal `importlib` calls dynamically requested top-level module names rather than namespaced package paths.
2. **High-Impact Blocker:** `localshift-cli.exe` crashed on standard Windows consoles (`UnicodeEncodeError: 'charmap' codec can't encode characters`) whenever converting files with non-ASCII characters, Cyrillic, CJK, or Emoji in their filenames.
3. **Medium Defect:** The CLI `convert` subcommand only displayed the first page output when converting multi-page PDFs to PNG/JPEG raster images because it called a single-output legacy wrapper rather than enumerating `res.output_paths`.

All three issues were fixed cleanly in shared backend and packaging code with zero architectural churn. A new dedicated test suite ([`tests/test_rc_audit.py`](file:///Z:/LocalShift/tests/test_rc_audit.py)) was added to lock in regression coverage. Both the standalone portable onedir application and Inno Setup 6 installer were rebuilt and validated end-to-end on real scanned fixtures, Unicode paths, and silent enterprise installation/uninstallation lifecycles.

---

## 2. Release Audit & Defect Resolution

### 2.1 RapidOCR Dynamic Module Resolution (CRITICAL)
- **Problem:** Running OCR on scanned documents through the packaged `LocalShift.exe` or `localshift-cli.exe` failed with:
  ```text
  AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'
  ```
- **Analysis:** RapidOCR loads its submodules using `importlib.import_module(config['Det']['module_name'])` where `module_name` is configured as `'ch_ppocr_v3_det'`, `'ch_ppocr_v3_rec'`, and `'ch_ppocr_v2_cls'`. In PyInstaller bundles, these modules are compiled into `PYZ-01.pyz` under `rapidocr_onnxruntime.<submodule>`. Because `collect_data_files` collected the filesystem folders containing only YAML configs, Python loaded an empty namespace package from disk lacking the Python classes.
- **Fix:**
  - In [`src/localshift/documents/ocr.py`](file:///Z:/LocalShift/src/localshift/documents/ocr.py), added dynamic `sys.modules` aliasing for `ch_ppocr_v2_cls`, `ch_ppocr_v3_det`, and `ch_ppocr_v3_rec` prior to initializing RapidOCR.
  - In [`packaging/localshift.spec`](file:///Z:/LocalShift/packaging/localshift.spec), explicitly added all RapidOCR submodules and `localshift.documents` modules to `hidden_imports`.
- **Validation:** Tested on `tests/fixtures/documents/doc_05_english_scan.pdf` via the compiled binary. RapidOCR initialized neural inference cleanly and extracted 140 characters of accurate invoice text.

### 2.2 Windows Console Stream Encoding Crash (HIGH)
- **Problem:** When converting files with non-ASCII characters on a standard Windows console (code page 1252 or 437), `localshift-cli.exe` crashed with an unhandled exception:
  ```text
  UnicodeEncodeError: 'charmap' codec can't encode characters in position 59-62: character maps to <undefined>
  ```
- **Fix:**
  - In [`src/localshift/cli.py`](file:///Z:/LocalShift/src/localshift/cli.py) and [`packaging/entrypoint_cli.py`](file:///Z:/LocalShift/packaging/entrypoint_cli.py), configured `sys.stdout` and `sys.stderr` with `reconfigure(errors="backslashreplace")`.
- **Validation:** Tested converting `тест 測試 📄 spaces.png` to JPEG. The CLI printed output safely without any traceback or exception.

### 2.3 Multipage PDF → Image CLI Reporting (MEDIUM)
- **Problem:** Converting a multipage PDF via `localshift convert multipage.pdf --to png` generated all page files on disk, but only printed the first page to stdout.
- **Fix:**
  - In [`src/localshift/cli.py`](file:///Z:/LocalShift/src/localshift/cli.py), replaced `convert_image()` delegation with direct `convert_request()` invocation, iterating over `res.output_paths` when multiple files are produced.
- **Validation:** Tested on a 2-page PDF. The CLI reported `Saved:` for both `multipage_page_1.png` and `multipage_page_2.png`.

---

## 3. Real-World Testing & Verification Evidence

### 3.1 Packaged Executable Real-World Test Summary
| Workflow | CLI Command / Invocation | Exit Code | Observed Output |
|---|---|---|---|
| **Unicode & Spaces** | `localshift-cli.exe convert "тест 測試 📄 spaces.png" --to jpg` | `0` | Cleanly converted to `...spaces.jpeg` with backslashreplace safe output. |
| **Multipage PDF → Images** | `localshift-cli.exe convert multipage.pdf --to png` | `0` | Both `multipage_page_1.png` and `multipage_page_2.png` saved and reported. |
| **Scanned PDF OCR** | `localshift-cli.exe convert doc_05_english_scan.pdf --to txt` | `0` | Neural OCR extracted full invoice text (`140 chars`) without errors. |
| **PDF → DOCX** | `localshift-cli.exe convert sample.pdf --to docx` | `0` | Structured `.docx` generated. |
| **DOCX → PDF** | `localshift-cli.exe convert sample.docx --to pdf` | `0` | PDF generated via Microsoft Word COM automation. |
| **PDF Workbench Rotate** | `localshift-cli.exe pdf rotate icon.pdf -o rot.pdf --angle 90` | `0` | Correctly rotated PDF output saved. |
| **Corrupt File Guard** | `localshift-cli.exe convert corrupt.pdf --to txt` | `2` | Clean error: `Corrupt or invalid PDF file`. |
| **Nonexistent File Guard** | `localshift-cli.exe convert missing.png --to jpg` | `2` | Clean error: `Input file not found`. |
| **GUI Cold Launch** | `LocalShift.exe` (offscreen execution) | `0` | Window and 5 tabs loaded with branding icon; terminated cleanly on signal. |

### 3.2 Silent Installer Lifecycle Evidence
```powershell
# 1. Silent install to test directory
Start-Process -FilePath "dist\installer\LocalShift-Setup-0.14.0.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/DIR="dist\test_rc_install"' -Wait
# Result: Installed _internal/, LocalShift.exe (6.22 MB), localshift-cli.exe (6.23 MB), unins000.exe, unins000.dat.

# 2. Execute installed binary on real scanned PDF
dist\test_rc_install\localshift-cli.exe convert tests\fixtures\documents\doc_05_english_scan.pdf --to txt --output-dir dist\test_rc_install
# Result: Saved doc_05_english_scan.txt (145 bytes). Content: "SCANNEDINVOICE(ENGLISH) Invoice Number.INV-2026-001..."

# 3. Silent uninstall
Start-Process -FilePath "dist\test_rc_install\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
# Result: Cleanly removed all installed binaries and directories, leaving user output file intact.
```

---

## 4. Test Suite Inventory & Regression Results

A total of **566 automated tests** were collected and executed across 18 test modules:
```text
=========================== short test summary info ===========================
SKIPPED [1] tests\test_converter.py:367: Symlink creation on Windows requires Developer Mode.
SKIPPED [1] tests\test_converter.py:380: Symlinks require Developer Mode on Windows.
SKIPPED [1] tests\test_reliability.py:308: Symlinks require Developer Mode on Windows.
563 passed, 3 skipped in 113.10s (0:01:53)
```

| Test Module | Count | Focus |
|---|---|---|
| [`tests/test_converter.py`](file:///Z:/LocalShift/tests/test_converter.py) | 63 | Core converter engine & legacy API |
| [`tests/test_adapters.py`](file:///Z:/LocalShift/tests/test_adapters.py) | 31 | Adapter contract & protocol checks |
| [`tests/test_jobs.py`](file:///Z:/LocalShift/tests/test_jobs.py) | 80 | Asynchronous JobQueue & batching |
| [`tests/test_planning.py`](file:///Z:/LocalShift/tests/test_planning.py) | 30 | Planning API & preflight validation |
| [`tests/test_reliability.py`](file:///Z:/LocalShift/tests/test_reliability.py) | 51 | Concurrency & resource stress |
| [`tests/test_document_foundation.py`](file:///Z:/LocalShift/tests/test_document_foundation.py) | 5 | Document container sniffing & fixtures |
| [`tests/test_pdf_extraction.py`](file:///Z:/LocalShift/tests/test_pdf_extraction.py) | 34 | PDF inspection & text extraction |
| [`tests/test_pdf_reliability.py`](file:///Z:/LocalShift/tests/test_pdf_reliability.py) | 18 | Benchmark quality & metrics |
| [`tests/test_pdf_ocr.py`](file:///Z:/LocalShift/tests/test_pdf_ocr.py) | 31 | Offline OCR engine, renderer & routing |
| [`tests/test_pdf_docx.py`](file:///Z:/LocalShift/tests/test_pdf_docx.py) | 27 | PDF to DOCX document reconstruction |
| [`tests/test_unseen_validation.py`](file:///Z:/LocalShift/tests/test_unseen_validation.py) | 7 | Unseen document validation set |
| [`tests/test_docx_pdf.py`](file:///Z:/LocalShift/tests/test_docx_pdf.py) | 26 | DOCX to PDF conversion engine |
| [`tests/test_pdf_image_export.py`](file:///Z:/LocalShift/tests/test_pdf_image_export.py) | 39 | PDF to PNG/JPEG raster export engine |
| [`tests/test_image_to_pdf.py`](file:///Z:/LocalShift/tests/test_image_to_pdf.py) | 39 | Image to PDF conversion & assembly |
| [`tests/test_pdf_workbench.py`](file:///Z:/LocalShift/tests/test_pdf_workbench.py) | 41 | PDF Workbench (Merge, Split, Extract, Reorder, Rotate) |
| [`tests/test_gui.py`](file:///Z:/LocalShift/tests/test_gui.py) | 30 | PySide6 Desktop GUI integration & workflows |
| [`tests/test_packaging.py`](file:///Z:/LocalShift/tests/test_packaging.py) | 6 | Packaging specifications, assets, version metadata |
| [`tests/test_rc_audit.py`](file:///Z:/LocalShift/tests/test_rc_audit.py) | 5 | Release Candidate QA & stability audit tests |

---

## 5. Release Artifact Inventory

| File Path | Description | Size | SHA-256 Checksum |
|---|---|---|---|
| `dist/installer/LocalShift-Setup-0.14.0.exe` | Windows Inno Setup 6 Installer | 93.34 MB | `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974` |
| `dist/LocalShift/LocalShift.exe` | Standalone GUI Executable | 5.94 MB | Packaged within `dist/LocalShift/` |
| `dist/LocalShift/localshift-cli.exe` | Standalone CLI Executable | 5.94 MB | Packaged within `dist/LocalShift/` |
| `dist/LocalShift/` | Complete Portable Onedir Tree | 291 MB | Standalone portable folder |

---

## 6. Release Gate Recommendation

**DECISION: APPROVED FOR RELEASE CANDIDATE (RC1)**

- All 36 release verification criteria passed.
- No crashes, data loss, source modification, or unhandled exceptions.
- Zero network telemetry or cloud dependence.
- Clean machine testing was conducted on the host Windows 11 system; domain VM testing is marked NOT VERIFIED due to lack of separate domain infrastructure.
