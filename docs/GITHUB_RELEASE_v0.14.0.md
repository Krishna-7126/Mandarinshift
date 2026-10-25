# LocalShift v0.14.0 — Offline-First Windows File Converter & Document Workbench

**Release Date:** October 26, 2026  
**Tag:** `v0.14.0`  
**Target OS:** Windows 10 / Windows 11 (64-bit AMD64)  
**License:** MIT License (Commercially permissive open-source)  

LocalShift is a free, privacy-first Windows desktop application and command-line tool for converting documents and images completely offline. It requires zero cloud connectivity, collects zero telemetry, and guarantees that your original files are never altered or overwritten.

---

## Highlights & Features

### 1. Unified PySide6 Desktop GUI (`LocalShift.exe`)
- Clean, responsive, native Windows desktop interface with five dedicated workflow tabs:
  - **File Converter:** Multi-format batch image and document converter.
  - **PDF ↔ DOCX:** Document interchange (PDF to editable Microsoft Word with table/heading reconstruction; DOCX to PDF with live backend discovery).
  - **PDF → Images:** Multi-page PDF rasterizer with configurable DPI (72–400), JPEG quality, page range parsing (`1-3, 5`), and tokenized filenames.
  - **Images → PDF:** Multi-image ordered assembly into a single PDF with page sizing (`A4`, `Letter`, `Original`), fitting (`contain`, `cover`), and margins.
  - **PDF Workbench:** Offline PDF merge, split, extract, reorder, and rotate (90°, 180°, 270°).
- Responsive background worker threads (`QThread`) with live progress bars and cooperative cancellation.

### 2. High-Performance Console CLI (`localshift-cli.exe`)
- Full command-line interface for PowerShell scripts, automated batch jobs, and enterprise workflows:
  ```powershell
  # Convert any file
  localshift-cli.exe convert document.pdf --to docx
  localshift-cli.exe convert photo.png --to webp

  # PDF Workbench operations
  localshift-cli.exe pdf merge doc1.pdf doc2.pdf -o merged.pdf
  localshift-cli.exe pdf rotate scan.pdf -o rotated.pdf --angle 90
  localshift-cli.exe pdf split book.pdf --pages 1-5 --output-dir ./chapters
  ```

### 3. Fully Offline OCR & Document Intelligence
- Bundled RapidOCR engine with ONNX Runtime CPU inference and pre-trained PP-OCR models.
- Automatic upside-down (180°) and sideways (90°/270°) scan orientation recovery.
- High-fidelity table detection, borderless financial ledger parsing, and reading order reconstruction.

### 4. Enterprise Safety & Immutability Guarantees
- **Source Immutability:** Source files are opened read-only and are strictly immutable.
- **Collision Protection:** Never overwrites existing destination files; appends ` (1)`, ` (2)` safely.
- **Atomic File Placement:** Conversions write to local temporary files first and atomically rename upon completion.

---

## Release Artifacts & Checksums

| File | Description | Size | SHA-256 Checksum |
|---|---|---|---|
| **`LocalShift-Setup-0.14.0.exe`** | Windows Inno Setup Installer | 93.34 MB | `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974` |
| **`LocalShift-v0.14.0-windows-x64.zip`** | Portable Standalone Bundle | 146.26 MB | `de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2` |

### Verification Command (PowerShell)
```powershell
Get-FileHash -Algorithm SHA256 .\LocalShift-Setup-0.14.0.exe
```

---

## Installation & Deployment

### Standard User Installation
1. Download `LocalShift-Setup-0.14.0.exe`.
2. Double-click the installer and follow the setup wizard.
3. Launch **LocalShift** from the Start Menu or Desktop.

### Silent Enterprise Deployment (IT / System Administrators)
```powershell
# Silent machine installation
.\LocalShift-Setup-0.14.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

# Silent uninstallation
"${env:ProgramFiles}\LocalShift\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

### Portable Run (Zero Installation)
Extract the portable distribution folder and run `LocalShift.exe` (GUI) or `localshift-cli.exe` (CLI) directly.

---

## Windows SmartScreen Advisory

Because LocalShift is a free, community open-source project without a commercial $400/yr EV Authenticode certificate:
- Microsoft SmartScreen will display an informational banner: *"Windows protected your PC — Microsoft Defender SmartScreen prevented an unrecognized app from starting"*.
- **To proceed:** Click **More info** → **Run anyway**.
- The binary contains zero trackers, analytics, telemetry, or external network requests.
