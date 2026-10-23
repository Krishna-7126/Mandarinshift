# LocalShift — Milestone Work Report LS-BE-006B
## PDF Inspection & Native Text Extraction Engine

**Milestone:** LS-BE-006B  
**Date:** 2026-10-23  
**Status:** COMPLETE  
**Component:** Backend Document Engine & PDF Processing Layer  

---

### 1. Executive Summary

Milestone **LS-BE-006B** introduces LocalShift's first functional document processing backend:
- Implemented a robust, standalone PDF inspection and heuristic classification layer (`localshift.documents.pdf_inspector.PdfInspector`).
- Implemented deterministic, page-by-page native text extraction using `pypdfium2` (`localshift.documents.text_extractor.NativePdfTextExtractor`) with cooperative cancellation, bounds enforcement, and Unicode preservation.
- Implemented and registered `PdfDocumentAdapter` in `default_registry`, providing a live, fully verified `PDF -> TXT` conversion route through the core conversion engine (`convert_request()`).
- Updated capability discovery and format registries so that `pdf` is discovered as a source format and `txt` as a target format, expanding available conversion routes to 21 while preserving 100% backward compatibility for all existing image conversion routes and CLI behaviors.
- Created 31 new automated tests covering born-digital, multi-page, multi-column, table, scanned, encrypted, and corrupted PDFs, achieving a total suite of 291 passing tests (3 skipped for Windows symlink privilege requirements, 0 failed).

---

### 2. Git State and Baseline

- **Initial Base Commit:** `17a93f489597218be5e1a0ad73111a0c15e52bdf`
- **Initial Test Baseline:** 259 passed, 3 skipped, 0 failed.
- **Environment:** Windows 11, Python 3.14.3 (`win32`).
- **Working Tree:** All changes are currently cleanly tracked in the working tree.

---

### 3. Actual Architecture Changes

1. **`localshift.documents` Package**:
   - `pdf_inspector.py`: `PdfInspector` parses PDF structure using `pypdfium2`, extracting page counts, physical point dimensions, orientation/rotation degrees, encryption status, character counts, text previews, and heuristics-based page classification (`TEXT_PRESENT`, `IMAGE_LIKELY`, `MIXED_OR_UNCERTAIN`, `EMPTY_OR_UNKNOWN`, `UNREADABLE`).
   - `text_extractor.py`: `NativePdfTextExtractor` extracts Unicode text page-by-page, enforcing a default `MAX_PAGES_LIMIT = 2000`, cooperative cancellation hooks, and structured `DocumentExtractionResult` output with configurable page separators.
   - `adapter.py`: `PdfDocumentAdapter` implements the `ConversionAdapter` protocol for directional route `("pdf", "txt")` with option support for `page_separator`.
2. **Central Registry & Formats**:
   - `localshift.formats`: Added canonical format descriptors for `pdf` (source format) and `txt` (target format), updated `sniff_format` with `%PDF-` magic-byte checking, and updated `PIL_FORMATS` mapping to filter out non-image formats.
   - `localshift.registry`: Automatically registers `PdfDocumentAdapter` alongside `PillowImageAdapter` at module import time.
   - `localshift.converter`: Updated result verification to permit legitimate 0-byte `.txt` outputs when converting born-digital PDFs or scans without extractable text, while maintaining strict non-empty checks for raster image formats.
   - `localshift.jobs`: Updated submission validation so unproducible target formats (including `pdf`) eagerly raise `ValueError` matching documented queue behavior.

---

### 4. Files Created and Modified

#### Files Created:
- `src/localshift/documents/__init__.py`: Package entry point exposing inspector, extractor, and adapter.
- `src/localshift/documents/pdf_inspector.py`: PDF inspection and heuristic classification.
- `src/localshift/documents/text_extractor.py`: Native text extraction engine.
- `src/localshift/documents/adapter.py`: `PdfDocumentAdapter` conversion adapter.
- `tests/test_pdf_extraction.py`: 31 test cases covering inspection, extraction, conversion, cancellation, options, and error handling.
- `docs/reports/LS-BE-006B-work-report.md`: This milestone report.

#### Files Modified:
- `pyproject.toml`: Added `pypdfium2>=4.30.0` dependency.
- `README.md`: Documented PDF-to-TXT conversion, inspection capabilities, and limitations.
- `src/localshift/__init__.py`: Exported document classes and updated `__all__`.
- `src/localshift/formats.py`: Added `pdf` and `txt` to canonical registry and added `%PDF-` sniffing.
- `src/localshift/registry.py`: Registered `PdfDocumentAdapter` in `default_registry`.
- `src/localshift/converter.py`: Allowed empty text outputs for text targets.
- `src/localshift/jobs.py`: Validated target format against registry supported targets at submission time.
- `tests/test_converter.py`: Updated format discovery tests for `pdf` and `txt`.
- `tests/test_planning.py`: Updated capability discovery tests for 21 supported routes.

---

### 5. Dependencies and Versions

- **`pypdfium2` version:** `5.14.0` (compiled with PDFium Chromium build `7584`).
- **Python Compatibility:** Python 3.14.3 Windows x64.
- **Pillow version:** `11.1.0`.

---

### 6. License and Redistribution Review

- **Library:** `pypdfium2`
- **License:** Dual-licensed under **Apache-2.0** and **BSD-3-Clause**.
- **Underlying Engine:** Google PDFium (Chromium project), licensed under **BSD-3-Clause**.
- **Redistribution Conditions:** Freely redistributable in source and binary forms with copyright notices preserved.
- **Prohibited Dependencies Avoided:**
  - `PyMuPDF` (AGPL-3.0) — strictly avoided.
  - `pdf2docx` (AGPL-3.0) — strictly avoided.
  - OCR native libraries (Tesseract / EasyOCR) — deferred to LS-BE-006C under permissive licenses.

---

### 7. PDF Inspection Behavior

The `PdfInspector` safely reads PDF files without executing arbitrary JavaScript or loading untrusted fonts:
- **Readable PDF Check:** Attempts document opening with error capture; unreadable or corrupt documents return `is_readable = False` with descriptive error strings rather than crashing.
- **Encryption Check:** Traps PDFium password-protection exceptions; sets `is_encrypted = True`, `is_readable = False`.
- **Dimensions and Orientation:** Returns page width and height in typographic points (1/72 inch) and rotation angle (0, 90, 180, 270 degrees).
- **Text Density Analysis:** Calculates character counts and generates previews (up to 120 chars) for diagnostics.

---

### 8. Text Extraction Behavior

- **Engine:** Google PDFium via `pypdfium2.PdfPage.get_textpage().get_text_range()`.
- **Determinism:** Extracting the same PDF always yields the identical byte and character stream.
- **Encoding:** Explicitly written and decoded as UTF-8.
- **Page Separators:** Configurable with default `\n\n--- Page {page} ---\n\n`.
- **Boundaries:** 1-based page numbering in user-facing diagnostics.

---

### 9. Classification Limitations

Classification is heuristic and communicates uncertainty:
- `TEXT_PRESENT`: Character count exceeds threshold (default ≥ 25 characters). Indicates extractable native text.
- `SPARSE_TEXT` / `MIXED_OR_UNCERTAIN`: Character count between 1 and 24 characters. May represent headers, page numbers, or vector labels.
- `IMAGE_LIKELY`: 0 extractable native characters. The page is likely a scan, photograph, or rasterized graphic, but could also contain vector outlines or DRM-restricted fonts.
- `UNREADABLE`: Per-page extraction failure due to corrupt stream objects.

*Caution: Native text extraction cannot determine if an embedded image inside a page contains textual content without OCR.*

---

### 10. Conversion Route and Capability Discovery

| Capability | Status |
|---|---|
| Total Registered Routes | 21 routes (20 image-to-image + 1 PDF-to-TXT) |
| Source Formats | `bmp`, `jpeg`, `pdf`, `png`, `tiff`, `webp` |
| Target Formats | `bmp`, `jpeg`, `png`, `tiff`, `txt`, `webp` |
| Route `pdf` → `txt` | **Supported & Active** (`PdfDocumentAdapter`) |
| Route `pdf` → `docx` | **Deferred** (LS-BE-006D) |
| Route `*` → `pdf` | **Not Supported** |

---

### 11. Security and Resource Limits

1. **Page Bound:** `MAX_PAGES_LIMIT = 2000` prevents decompression bombs from exhausting heap memory.
2. **File Size Bound:** Aligned with core `MAX_INPUT_BYTES = 250 MiB`.
3. **Cancellation:** `cancel_check` callable polled before every page extraction.
4. **Temporary Output:** Created using `tempfile.mkstemp` on the destination volume and atomically renamed via `os.replace`.
5. **Path Traversal & Collision:** Destination paths reserved using `reserve_output_path()`; existing files receive Windows-style collision suffixes `(2)`, `(3)`.

---

### 12. Benchmark Fixtures

All 10 benchmark fixtures from LS-BE-006A were evaluated:
- `doc_01_simple_digital.pdf`: Clean extraction (159 chars).
- `doc_02_multipage_digital.pdf`: 3-page extraction with page separators.
- `doc_03_multicolumn.pdf`: Multi-column flow preserved.
- `doc_04_table.pdf`: Grid table text preserved.
- `doc_05_english_scan.pdf`: Correctly identified as `IMAGE_LIKELY` (0 chars), conversion emits scan warning.
- `doc_06_hindi_scan.pdf`: Correctly identified as `IMAGE_LIKELY` (0 chars).
- `doc_07_mixed_pages.pdf`: Multi-page inspection classifies individual pages.
- `doc_08_rotated_page.pdf`: 90-degree rotation detected with diagnostic warning.
- `doc_09_corrupt.pdf`: Handled cleanly with `is_readable = False` and safe failure.
- `doc_10_encrypted.pdf`: Handled cleanly with password-protection error.

---

### 13. Test Results

Command executed:
`$env:PYTHONPATH="src"; py -3.14 -m pytest -v --tb=short`

```text
tests/test_adapters.py ...............................                   [ 10%]
tests/test_converter.py ................................................ [ 26%]
...ss..........                                                          [ 31%]
tests/test_document_foundation.py .....                                  [ 33%]
tests/test_jobs.py ..................................................... [ 51%]
...........................                                              [ 60%]
tests/test_pdf_extraction.py ...............................             [ 71%]
tests/test_planning.py ..............................                    [ 81%]
tests/test_reliability.py .....................s........................ [ 97%]
........                                                                 [100%]

291 passed, 3 skipped in 2.92s
```
- Total test cases: 294
- Passing: 291
- Skipped: 3 (Windows non-admin symlink privilege checks)
- Failed: 0

---

### 14. Known Bugs and Limitations

1. **OCR Missing:** Scanned PDFs produce 0-byte or empty text output with warnings; OCR engine is scheduled for LS-BE-006C.
2. **Complex Layout Reading Order:** Reading order in multi-column or floating-table layouts relies on PDF stream order; complex multi-frame newspaper layouts may interleave columns without paragraph restructuring.
3. **No PDF Target Generation:** LocalShift only reads PDF; converting images or documents to PDF is out of scope for this milestone.

---

### 15. Installation Commands

To reproduce the environment:
```powershell
python -m pip install pypdfium2>=4.30.0 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

---

### 16. Git Commit Status

- Changes are currently **uncommitted** in the local working tree.
- Awaiting explicit instruction or confirmation before committing.

---

### 17. Recommended Next Milestone

- **LS-BE-006C:** Offline OCR Engine Foundation (permissively licensed OCR integration for scanned pages and embedded images).
- **LS-BE-006D:** Document Reconstruction & PDF-to-DOCX Generation.

---

### 18. Decisions Requiring Approval

1. Approval to commit working tree changes with commit message: `LS-BE-006B: PDF inspection, native text extraction, and PDF-to-TXT adapter`.
2. Decision on whether to proceed immediately to **LS-BE-006C** (OCR Engine Foundation).

---

**FINAL STATUS:** COMPLETE
