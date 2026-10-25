# LocalShift — Changelog

All notable changes to the LocalShift project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
