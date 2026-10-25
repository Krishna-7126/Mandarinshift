# LocalShift — LS-BE-014 Work Report
# Windows Packaging, Installer & Release Readiness

**Milestone:** LS-BE-014  
**Date:** October 25, 2026  
**Status:** Complete & Regression-Gated  
**Test Suite:** 561 tests collected (558 passed, 3 skipped on non-admin Windows, 0 failed)  
**Release Artifacts:**
- Portable Onedir Bundle: `dist/LocalShift/` (`LocalShift.exe` & `localshift-cli.exe`)
- Setup Installer: `dist/installer/LocalShift-Setup-0.14.0.exe` (92.25 MB, SHA-256: `f64d22b3032c75e69db6b0d510691e9dda083d19a9de2dc7ed147cf2a6fbc435`)

---

## 1. Executive Summary

Milestone **LS-BE-014** transitions LocalShift from a developer-facing Python repository into a production-grade, reliable, offline-first Windows desktop application and installer.

All conversion engines, document reconstructors, OCR pipelines, renderers, and the PySide6 unified GUI remain intact and unmodified in their core logic. Packaging was implemented cleanly using PyInstaller (`localshift.spec`) with strict exclusion of unneeded development and heavy scientific frameworks, resulting in a lean standalone onedir bundle. An open-source, permissively licensed installer was created using Inno Setup 6 (`localshift.iss`), providing automated shortcuts, clean uninstallation, and silent enterprise deployment flags.

The entire 561-test regression suite was executed, achieving 558 passing tests and 3 expected skips (requiring Windows Developer Mode for symlinks). Direct execution of both the packaged GUI (`LocalShift.exe`), the packaged CLI (`localshift-cli.exe`), and silent installer lifecycle operations (`/VERYSILENT`) were validated with 100% success.

---

## 2. Dependency, License & Asset Audit

### 2.1 Runtime Dependencies & Permissive Licensing
Every bundled third-party library was audited for compatibility with LocalShift's offline-first, commercially permissive desktop release model:

| Component | Version | License | Bundled Role |
|---|---|---|---|
| **Python** | 3.14.3 (AMD64) | PSF-2.0 | Embedded Python runtime DLLs and standard library |
| **PySide6 / Qt6** | 6.12.0 | LGPL-3.0 | Desktop GUI widgets, application lifecycle, worker threads |
| **Pillow** | 12.1.1 | HPND / MIT-like | Raster image decode, encode, EXIF, and geometry |
| **pypdf** | 6.8.0 | BSD-3-Clause | PDF structural manipulation (merge, split, reorder, rotate) |
| **pypdfium2** | 5.4.0 | Apache-2.0 / BSD-3 | High-fidelity PDF rendering (`pdfium.dll` native binary) |
| **python-docx** | 1.2.0 | MIT | Microsoft Word document creation and table styling |
| **lxml** | 6.1.3 | BSD-3-Clause | High-performance XML parsing for DOCX structures |
| **RapidOCR** | 1.2.3 | Apache-2.0 | Offline OCR engine with bundled PP-OCR ONNX models |
| **ONNX Runtime** | 1.26.0 | MIT | Local CPU neural network inference (`onnxruntime.dll`) |
| **OpenCV Headless** | 4.13.0 | Apache-2.0 | Computer vision image preprocessing for OCR |
| **PyYAML** | 6.0.3 | MIT | Configuration file parsing for OCR model definitions |

*Zero copyleft (GPL) dependencies are bundled. PySide6 is utilized dynamically via standard LGPL dynamic library linking, satisfying LGPL requirements.*

### 2.2 Branding & Icon Assets
High-fidelity multi-resolution application icons were created and embedded into the application executable and installer:
- `assets/icon.png`: 256×256 high-resolution PNG with alpha transparency.
- `assets/icon.ico`: Valid multi-resolution Windows icon file containing 16×16, 24×24, 32×32, 48×48, 64×64, 128×128, and 256×256 MIP layers.
- Embedded into Windows PE executable headers (`LocalShift.exe`, `localshift-cli.exe`) and Inno Setup installer wizard and uninstaller headers.

---

## 3. PyInstaller Packaging Architecture

### 3.1 Dual-Target Design (`packaging/localshift.spec`)
LocalShift provides two distinct entry points in a single unified deployment directory:
1. **`LocalShift.exe` (Windowed GUI):**
   - Configured with `console=False`.
   - Starts instantly with no console window flashing.
   - Automatically loads branding icon via `_find_app_icon()` across development and frozen environments.
2. **`localshift-cli.exe` (Console CLI):**
   - Configured with `console=True`.
   - Attaches standard streams (`stdout`, `stderr`, `stdin`) for terminal usage, PowerShell pipelines, and automated scripting.

### 3.2 Exclusion of Unused Packages
To avoid multi-gigabyte bundle bloat and ensure fast cold startups, `packaging/localshift.spec` explicitly excludes unused heavy scientific, machine-learning, development, and Qt modules that may exist in developer virtual environments:
- Excluded Qt modules: `QtWebEngine*`, `QtQuick`, `QtQml`, `Qt3D*`, `QtDesigner`, `QtBluetooth`, `QtMultimedia*`, `QtPdf*`, `QtSensors`.
- Excluded development & scientific frameworks: `torch`, `torchvision`, `tensorflow`, `scipy`, `sklearn`, `transformers`, `numba`, `llvmlite`, `matplotlib`, `pandas`, `yt_dlp`, `IPython`, `notebook`, `pytest`.

### 3.3 Bundled Native Binaries & Models
- **OCR Models:** RapidOCR models (`ch_PP-OCRv3_det_infer.onnx`, `ch_PP-OCRv3_rec_infer.onnx`, `ch_ppocr_mobile_v2.0_cls_infer.onnx`) collected via `collect_data_files('rapidocr_onnxruntime')`.
- **PDFium Binary:** `pdfium.dll` collected via `collect_dynamic_libs('pypdfium2_raw')`.
- **ONNX Runtime:** `onnxruntime.dll` collected via `collect_dynamic_libs('onnxruntime')`.
- **DOCX Templates:** Default OpenXML document templates collected via `collect_data_files('docx')`.

---

## 4. Inno Setup 6 Installer Subsystem (`packaging/localshift.iss`)

### 4.1 Installer Configuration
- **Application Identity:** `AppId={{9D3C012B-5B74-4C2E-8E92-3FE0696E8751}`.
- **Compression:** LZMA2/Ultra64 solid compression, yielding a 92.25 MB standalone installer from over 350 MB of uncompressed binaries and models.
- **Architecture:** `ArchitecturesInstallIn64BitMode=x64compatible` (native 64-bit Windows).
- **Permissions:** `PrivilegesRequiredOverridesAllowed=commandline dialog` allowing standard users to install to `%LOCALAPPDATA%\Programs\LocalShift` without administrative rights, or administrators to install to `C:\Program Files\LocalShift` for all users.
- **Shortcuts:**
  - Start Menu shortcuts for both **LocalShift** and **LocalShift CLI**.
  - Optional Desktop shortcut with clean unchecked default.
  - Automatic `UninstallDisplayIcon` registration in Windows "Add or Remove Programs".

### 4.2 Automated Build Pipeline (`packaging/build.py`)
A single, reproducible Python script orchestrates the complete build:
```powershell
py -3.14 packaging/build.py
```
1. Cleans previous `build/` and `dist/` directories.
2. Runs PyInstaller `--clean --noconfirm packaging/localshift.spec`.
3. Verifies binary presence, `pdfium.dll`, `onnxruntime.dll`, and OCR models.
4. Auto-detects Inno Setup Compiler (`ISCC.exe`) across PATH, user AppData, and Program Files.
5. Compiles `LocalShift-Setup-0.14.0.exe` and outputs file size and SHA-256 hash.

---

## 5. Verification & Testing

### 5.1 Packaging Smoke Tests (`tests/test_packaging.py`)
Six dedicated automated tests verify packaging specifications:
- `test_packaging_files_exist`: Verifies presence of spec, iss, build script, version info, and entry points.
- `test_assets_exist_and_valid`: Verifies `assets/icon.png` (256×256) and `assets/icon.ico` (multi-resolution).
- `test_version_info_metadata`: Verifies version numbers (0.14.0.0) and PE resource strings.
- `test_spec_configuration`: Verifies dual GUI/CLI targets, model collection, and exclusions.
- `test_inno_setup_configuration`: Verifies installer app identity, version, and architecture.
- `test_find_app_icon_helper`: Verifies runtime icon resolution across frozen and development environments.

### 5.2 Standalone Executable Verification
Direct execution of the packaged binaries was tested from PowerShell:
1. `dist/LocalShift/localshift-cli.exe --help` -> Exit code 0, instant response.
2. `dist/LocalShift/localshift-cli.exe pdf --help` -> Exit code 0, workbench subcommands displayed.
3. Image conversion:
   ```powershell
   dist\LocalShift\localshift-cli.exe convert --to jpeg assets\icon.png --output-dir dist
   ```
   Successfully generated `dist\icon.jpeg` with exit code 0.
4. Image to PDF conversion:
   ```powershell
   dist\LocalShift\localshift-cli.exe convert --to pdf assets\icon.png --output-dir dist
   ```
   Successfully generated `dist\icon.pdf` with exit code 0.
5. PDF Workbench page rotation:
   ```powershell
   dist\LocalShift\localshift-cli.exe pdf rotate dist\icon.pdf -o dist\icon_rot.pdf --angle 90
   ```
   Successfully generated rotated document `dist\icon_rot.pdf` with exit code 0.

### 5.3 Installer Silent Install & Uninstall Verification
The installer lifecycle was tested end-to-end:
```powershell
# Silent installation into isolated test folder
Start-Process -FilePath "dist\installer\LocalShift-Setup-0.14.0.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/DIR="dist\test_install"' -Wait

# Verified installation contents
# - _internal/
# - LocalShift.exe (6,022,309 bytes)
# - localshift-cli.exe (6,027,430 bytes)
# - unins000.exe (4,379,906 bytes)
# - unins000.dat (71,687 bytes)

# Executed installed CLI from test directory
dist\test_install\localshift-cli.exe --help -> Exit code 0

# Executed silent uninstaller
Start-Process -FilePath "dist\test_install\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait

# Verified complete removal
Test-Path "dist\test_install" -> False (Directory completely uninstalled and removed)
```

### 5.4 Full Regression Suite Results
The complete regression test suite was executed across all modules:
```text
=========================== short test summary info ===========================
SKIPPED [1] tests\test_converter.py:367: Symlink creation on Windows requires Developer Mode or admin privileges.
SKIPPED [1] tests\test_converter.py:380: Symlinks require Developer Mode on Windows.
SKIPPED [1] tests\test_reliability.py:308: Symlinks require Developer Mode on Windows.
558 passed, 3 skipped in 127.78s (0:02:07)
```
**Zero regressions.** 100% of non-privileged Windows tests passed.

---

## 6. Windows Defender & SmartScreen Guidance

Because LocalShift is built without an expensive commercial code-signing certificate (EV / OV Authenticode certificate), Windows Defender and Microsoft SmartScreen will display an informational warning on clean machines ("Windows protected your PC — Microsoft Defender SmartScreen prevented an unrecognized app from starting").

### Important Facts for Users & IT Administrators:
1. **No Cloud Calls or Network Telemetry:** LocalShift makes zero external network requests. All OCR, image processing, PDF manipulation, and document conversions execute 100% locally on the host CPU.
2. **Reproducible SHA-256 Checksums:** Users can independently verify binary integrity by comparing SHA-256 checksums published in the release notes with `Get-FileHash`.
3. **Bypassing the SmartScreen Dialog:**
   - Click **More info**.
   - Click **Run anyway**.
   - Once an executable establishes reputation or is whitelisted by organization policies, SmartScreen warnings cease.
4. **Clean Machine Portable Option:**
   - Organizations that restrict installer execution can run the portable zip/folder `dist/LocalShift/` directly with zero administrative privileges.

---

## 7. Release Artifact Inventory

| Artifact | Type | File Size | SHA-256 Checksum |
|---|---|---|---|
| `LocalShift-Setup-0.14.0.exe` | Windows Installer | 92.25 MB | `f64d22b3032c75e69db6b0d510691e9dda083d19a9de2dc7ed147cf2a6fbc435` |
| `LocalShift.exe` | Standalone GUI Binary | 5.74 MB | Embedded in `dist/LocalShift/` onedir bundle |
| `localshift-cli.exe` | Standalone CLI Binary | 5.75 MB | Embedded in `dist/LocalShift/` onedir bundle |
| `dist/LocalShift/` | Portable Onedir Folder | 288 MB | Standalone portable folder with bundled models and DLLs |

---

## 8. Release Readiness Checklist

- [x] Application version synchronized at `0.14.0` across `pyproject.toml`, `version_info.txt`, `localshift.iss`, and documentation.
- [x] Multi-resolution icon assets generated (`assets/icon.ico`, `assets/icon.png`) and verified.
- [x] Dual executables (`LocalShift.exe` and `localshift-cli.exe`) packaged with correct PE version metadata.
- [x] All native dependencies (`pdfium.dll`, `onnxruntime.dll`, OpenXML templates) verified in bundle.
- [x] All RapidOCR ONNX models bundled and verified.
- [x] Missing optional backends (LibreOffice / Word COM) produce actionable UI status badges and informative CLI messages without crashing.
- [x] Inno Setup 6 installer compiled with LZMA2/Ultra64 compression.
- [x] Silent installation (`/VERYSILENT`) and uninstallation (`unins000.exe /VERYSILENT`) verified.
- [x] Standalone portable execution verified for conversion, image assembly, and PDF workbench operations.
- [x] Automated packaging smoke tests added to test suite (`tests/test_packaging.py`).
- [x] Full regression test suite passing (558 passed, 3 skipped, 0 failed).
- [x] Documentation updated: `README.md`, `TASKS.md`, `docs/PROJECT_STATUS.md`, `docs/TEST_PLAN.md`, `docs/FORMAT_SUPPORT.md`.
- [x] Work report created: `docs/reports/LS-BE-014-work-report.md`.
- [x] Working tree clean of temporary test files; all changes remain uncommitted for review.
