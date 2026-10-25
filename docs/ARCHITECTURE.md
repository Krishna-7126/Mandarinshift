# LocalShift — Architectural Overview

**Version:** 0.12.0 (Updated: Milestone LS-BE-012)  
**System:** Offline-First Desktop Conversion Backend  

---

## 1. System Philosophy & Design Principles

LocalShift is built on three strict non-negotiables:
1. **Privacy First & 100% Offline:** Zero external network calls, zero analytics, zero document uploads. All conversion, document rendering, and OCR inference executes locally on the user's host.
2. **Untrusted Input Defense:** PDFs, DOCX files, images, and user-submitted files are treated as untrusted data. Strict bounds are enforced on file sizes (250 MiB), container structure (zip integrity and XML schema validation), page counts (2000 pages), rendering resolutions (72–400 DPI), and pixel memory ceilings (16 MP per page/image).
3. **Atomic & Collision-Safe I/O:** Conversions write to temporary files within safe directories and replace target files atomically. Existing files are never overwritten without explicit collision resolution (` (1)`, ` (2)`). Source files are opened read-only and never mutated.

---

## 2. Layered Backend Architecture

```
[ Conversion Request / CLI / GUI / API ]
                   │
                   ▼
       [ Conversion Planner & Preflight ]
                   │
                   ▼
           [ AdapterRegistry ]
          /        │        \            \
         ▼         ▼         ▼            ▼
[ PillowAdapter ] [ ImageToPdfAdapter ] [ DocxToPdfAdapter ]
   (img ⇄ img)       │                     │
                     │              (LibreOffice / Word COM)
                     ▼                     │
           [ PdfDocumentAdapter ] ─────────┘
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
  [ TXT Target ] [ DOCX Target ] [ PNG/JPEG Target ]
  (TextExtractor)(Reconstructor) (ImageExporter)
   /     \          /   │   \       │
  ▼       ▼        ▼    ▼    ▼    [ Renderer ]
  [Native] [OCR] [Tables][Images]   │
     │        │     │             (Pillow)
   (PDFium) [Renderer]
              │
          [RapidOCR]
```

---

## 3. Core Subsystems

### A. Document Inspection (`localshift.documents.pdf_inspector.PdfInspector`)
- Fast, non-rasterizing structural inspection of PDFs using Google PDFium (`pypdfium2`).
- Inspects object streams and page metadata to classify pages:
  - `TEXT_PRESENT`: Significant native character count (≥ 40 chars).
  - `IMAGE_LIKELY`: Raster graphic scan (0 native chars, embedded images).
  - `MIXED_OR_UNCERTAIN`: Sparse text (< 40 chars) or vector graphics.
  - `EMPTY_OR_UNKNOWN`: Blank page (0 text, 0 images).
  - `UNREADABLE`: Damaged xref or corrupted page stream.

### B. Bounded Page Rendering (`localshift.documents.renderer.PdfPageRenderer`)
- High-performance rasterization to RGB NumPy arrays.
- Respects ISO 32000 maximum page dimensions (14,400 points).
- Clamps rendering DPI to safe bounds (72–400 DPI, default 200 DPI).
- Automatically downscales rendering scale if estimated pixel count exceeds `MAX_IMAGE_PIXELS` (16,000,000 pixels ~ 48 MB RAM buffer).
- Hardened buffer memory ownership (`OWNDATA: True`) eliminates use-after-free risks when closing native PDFium bitmaps.

### C. Offline OCR Engine (`localshift.documents.ocr.RapidOcrEngine`)
- Local, CPU-first inference using RapidOCR (v1.2.3) and ONNX Runtime CPU (v1.26.0).
- Bundles lightweight, high-accuracy PP-OCRv4 ONNX models (~13.7 MB total):
  - Detection: `ch_PP-OCRv4_det_infer.onnx`
  - Recognition: `ch_PP-OCRv4_rec_infer.onnx`
  - Direction classification: `ch_ppocr_mobile_v2.0_cls_infer.onnx`
- Thread-safe singleton caching avoids re-initializing ONNX inference sessions across multiple pages or documents.

### D. Reading-Order Reconstruction (`localshift.documents.ocr.reconstruct_reading_order`)
- Heuristic 2D line-grouping algorithm:
  - Filters out degenerate boxes.
  - Groups bounding boxes into horizontal lines if vertical overlap exceeds 45% of minimum line height.
  - Sorts lines vertically from top to bottom.
  - Sorts words horizontally within each line from left to right.
  - Emits clean, paragraph-separated UTF-8 plain text.

### E. Per-Page Extraction & Routing (`localshift.documents.text_extractor.NativePdfTextExtractor`)
- Supported modes:
  - `"auto"`: Intelligent per-page routing (`TEXT_PRESENT` → native extraction; `IMAGE_LIKELY` → OCR; `EMPTY_OR_UNKNOWN` → blank; `MIXED_OR_UNCERTAIN` → hybrid merge without duplication).
  - `"native_only"`: Fast digital extraction bypassing rasterization and OCR.
  - `"force_ocr"`: Forces full-page rasterization and OCR on all pages.

### F. Structured DOCX Document Reconstruction (`localshift.documents.docx_builder.PdfToDocxReconstructor`)
- Reconstructs digital, scanned, and mixed PDFs into editable Microsoft Word (.docx) documents.
- **Headings:** Recovers multi-level headings (Levels 1–3) based on font size metrics, section numbering (`1.`, `1.1`), and uppercase title patterns.
- **Paragraphs:** Conservative line joining groups visual lines into coherent paragraphs while respecting list bullets (`- `, `* `, `• `) and sentence boundaries.
- **Tables:** Detects tabular structures from separator rules or aligned multi-column data, outputting native formatted Word tables (`Table Grid`).
- **Images:** Extracts embedded raster graphics from digital pages and embeds them as scalable Word pictures.
- **Orientation & Page Sequence:** Configures section orientation to landscape for rotated pages (90°/270°) and preserves multi-page sequence with page breaks.

### G. Offline DOCX → PDF Document Rendering (`localshift.documents.docx_renderer.DocxToPdfRenderer`)
- Dedicated rendering engine converting Microsoft Word documents (.docx) to PDF.
- **Backend Strategies:**
  - *LibreOffice Headless:* Uses `soffice.exe --headless --convert-to pdf` with an isolated user profile (`-env:UserInstallation`) to ensure sandbox isolation and eliminate profile lock contention.
  - *Microsoft Word COM Automation:* On Windows, uses PowerShell COM automation with non-interactive execution, read-only opening, and prompt suppression (`DisplayAlerts = 0`).
- **Dynamic Route Availability:** Checks system environment at capability query time. Does not advertise `("docx", "pdf")` unless at least one valid backend is discovered.
- **Sandboxed Execution & Immutability:** Source files are copied to an isolated temporary sandbox (`localshift_docx_render_*`). Renderers execute exclusively against sandboxed copies; source files are never opened with write locks or modified.
- **Subprocess Supervision:** Monitored via non-blocking polling loops supporting cooperative cancellation, strict timeouts (clamped 5–300s, default 60s), forced process termination (`kill()`), and complete temporary artifact cleanup.

### H. PDF Page Image Exporter (`localshift.documents.pdf_image_exporter.PdfToImageExporter`)
- High-resolution, bounded offline rasterization exporting single or multipage PDFs into individual PNG or JPEG image files.
- **Page Selection:** Supports `"all"`, single page, range (`"1-5"`), and comma-delimited lists (`"1, 3, 5"`), with strict bounds and syntax validation.
- **Batch Multipage Placement:** Manages atomic placement and collision protection across all generated pages. Single-page PDFs default to `{stem}.{ext}`, while multipage exports number pages sequentially (`{stem}_page_{page}.{ext}`).
- **Pattern Customization:** Supports configurable patterns with `{stem}`, `{page}`, `{page_count}`, and `{ext}` tokens, rejecting path traversal attempts.
- **Resource Ceiling:** Clamps DPI (72–400) and limits maximum raster pixels per page (16 MP) via `PdfPageRenderer`.

### I. Image → PDF Assembly Engine (`localshift.documents.image_to_pdf.ImageToPdfConverter` & `ImageToPdfAdapter`)
- Dedicated engine converting raster images (PNG, JPEG, WebP, BMP, TIFF) to PDF, supporting both 1:1 conversion and ordered multipage assembly.
- **Layout & Dimension Modes:**
  - `"original"` / `"fit_to_image"` matches exact image aspect ratio and dimensions at specified DPI.
  - Standard page sizes (`"a4"`, `"letter"`), with portrait/landscape or auto orientation matching aspect ratios.
  - `"contain"` mode scales proportionally within margins; `"cover"` mode fills printable area with centered cropping.
- **Compositing & Format Normalization:**
  - Strips alpha channels against configurable RGB background fill (`(255, 255, 255)` default).
  - Normalizes CMYK, Grayscale, and Paletted modes to RGB before writing.
  - Respects EXIF orientation tags (`ImageOps.exif_transpose`).
- **Ordered Multipage Assembly:**
  - Assembles multiple sources sequentially (`additional_sources`) with cooperative cancellation and memory limits per image.
  - Custom output naming via `output_name` with reservation and atomic placement.

### J. PDF Workbench Engine (`localshift.documents.pdf_workbench.PdfWorkbench`)
- High-performance, fully offline PDF structure and page manipulation engine.
- **Merge (`merge_pdfs`):** Sequentially combines multiple PDF files into one ordered output document with full page dimension, rotation, and media box preservation.
- **Split (`split_pdf`):** Extracts pages into individual single-page PDFs using flexible page syntax and configurable output naming tokens (`{stem}`, `{page}`, `{page_count}`, `{ext}`).
- **Extract (`extract_pdf_pages`):** Extracts page subsets into a single target PDF document without content re-encoding.
- **Reorder (`reorder_pdf_pages`):** Rearranges pages based on validated 1-based index sequences.
- **Rotate (`rotate_pdf_pages`):** Rotates selected or all pages by 90°, 180°, or 270° with relative (`(current + angle) % 360`) or absolute modes.
- **Integrity & Concurrency Controls:** Preflight inspection via `PdfInspector`, input source immutability, volume-local temporary file generation, in-process destination reservations (`reserve_output_path`), atomic replacement (`os.replace`), and cooperative cancellation.

---

## 4. Resource & Security Controls

| Resource | Boundary / Ceiling | Mechanism |
|---|---|---|
| Max File Size | 250 MiB | Checked at conversion entry point (`convert_request`) |
| Max Pages | 2000 pages | Enforced in `NativePdfTextExtractor`, `PdfToDocxReconstructor`, `PdfWorkbench` |
| Max Dimensions | 14,400 points | Verified in `PdfPageRenderer` |
| Max Raster Pixels | 16,000,000 pixels | Downscaled in `PdfPageRenderer` / Clamped in `ImageToPdfConverter` |
| DOCX Integrity | Magic bytes + zip integrity | Validated PK header + `word/document.xml` existence |
| Rendering Timeout | 5 to 300 seconds (default 60s) | Subprocess polling with process kill on expiry |
| Memory Limits | CPU inference | ONNX Runtime CPU provider; no GPU allocations |
| Cancellation | Cooperative | Polled between pages, before OCR, during workbench ops & rendering subprocess |
| Output Atomicity | Atomic rename | Written to temporary file and renamed atomically |


