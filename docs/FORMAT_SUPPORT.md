# LocalShift — Format Support Specification

**Version:** 0.14.0-RC1 (Updated: Milestone LS-BE-015)  
**Status:** Implemented, Packaged, Render-Validated & Release-Candidate Audited  

---

## 1. Supported Format Matrix

LocalShift conversion capabilities are explicit and directional. A format pair is available only if an adapter is registered for that route in the `AdapterRegistry`, and the adapter's offline backend requirements are satisfied.

### Canonical Formats

| Format Key | Category | Extensions | Default Sniffing | Role in LocalShift |
|---|---|---|---|---|
| `png` | Raster Image | `.png` | Magic bytes (`\x89PNG\r\n\x1a\n`) | Input & Output |
| `jpeg` | Raster Image | `.jpeg`, `.jpg` | Magic bytes (`\xff\xd8\xff`) | Input & Output |
| `webp` | Raster Image | `.webp` | Magic bytes (`RIFF....WEBP`) | Input & Output |
| `bmp` | Raster Image | `.bmp` | Magic bytes (`BM`) | Input & Output |
| `tiff` | Raster Image | `.tiff`, `.tif` | Magic bytes (`II*\x00` / `MM\x00*`) | Input & Output |
| `pdf` | Document | `.pdf` | Magic bytes (`%PDF-`) | Input & Output |
| `txt` | Plain Text | `.txt` | Plain text / UTF-8 | Output Only |
| `docx` | Word Document | `.docx` | Magic bytes (`PK\x03\x04` + `word/document.xml`) | Input & Output |

---

## 2. Directional Conversion Routes (30 Total)

### Image-to-Image Routes (20 Routes via `PillowImageAdapter`)
Every distinct pair among `{"png", "jpeg", "webp", "bmp", "tiff"}` is supported in both directions:
- `png` ⇄ `jpeg`, `png` ⇄ `webp`, `png` ⇄ `bmp`, `png` ⇄ `tiff`
- `jpeg` ⇄ `webp`, `jpeg` ⇄ `bmp`, `jpeg` ⇄ `tiff`
- `webp` ⇄ `bmp`, `webp` ⇄ `tiff`
- `bmp` ⇄ `tiff`

*Same-format conversion (e.g. `png` → `png`) is intentionally rejected as a no-op.*

### Document Routes (10 Routes)
- `pdf` → `txt` (via `PdfDocumentAdapter`): Hybrid native text extraction and offline OCR to UTF-8 plain text.
- `pdf` → `docx` (via `PdfDocumentAdapter`): Structured document reconstruction into editable Microsoft Word (.docx) documents with headings, paragraphs, bordered/borderless tables, bold headers, currency cells, image-caption flow, and page sequences.
- `pdf` → `png` (via `PdfDocumentAdapter` / `PdfToImageExporter`): High-resolution rasterization of single or multipage PDFs into individual PNG images with configurable DPI, page range selection, and custom file pattern formatting.
- `pdf` → `jpeg` (via `PdfDocumentAdapter` / `PdfToImageExporter`): Rasterization of PDF pages into JPEG images with configurable DPI, compression quality, custom background color fill, and flexible page selection.
- `docx` → `pdf` (via `DocxToPdfAdapter`): Offline document rendering translating Microsoft Word documents to PDF via headless LibreOffice or Microsoft Word COM automation, preserving headings, fonts, styles, tables, graphics, headers, footers, margins, and page orientation. Dynamic route discovery advertises the route only when an offline backend is installed.
- `png` → `pdf`, `jpeg` → `pdf`, `webp` → `pdf`, `bmp` → `pdf`, `tiff` → `pdf` (via `ImageToPdfAdapter` / `ImageToPdfConverter`): Offline conversion of single raster images or ordered assembly of multiple raster images into compliant PDF documents with configurable page size, fitting, orientation, margins, background color, DPI, and quality.

---

## 3. PDF Inspection, OCR & Extraction Behaviors

### Inspection (`PdfInspector`)
`localshift.documents.pdf_inspector.PdfInspector.inspect()` performs safe, non-rendering inspection of PDF structure via Google PDFium:
- **Readable Check:** Validates header, catalog, and xref tables. Corrupt PDFs return `is_readable = False` with structured error descriptions.
- **Encryption Check:** Traps password-protection errors; sets `is_encrypted = True`, `is_readable = False`.
- **Page Metrics:** Page dimensions (in 1/72-inch points) and page orientation / rotation (0, 90, 180, 270 degrees).
- **Object Inspection:** Inspects page dictionary objects (`PdfTextObj`, `PdfImage`, `PdfPath`) to categorize content.
- **Content Classification:**
  - `TEXT_PRESENT`: Page contains substantial extractable native text (≥ 40 characters) without embedded raster images.
  - `IMAGE_LIKELY`: Page contains zero native text and at least one embedded raster graphic object (`PdfImage`).
  - `MIXED_OR_UNCERTAIN`: Page contains sparse text (< 40 characters), a combination of text and image objects, or vector path elements.
  - `EMPTY_OR_UNKNOWN`: Page contains zero text and zero image/path objects (blank page).
  - `UNREADABLE`: Page stream damaged or corrupt.
- **Reading Order Diagnostics:** Detects vertical upward jumps or alternating horizontal stream coordinates indicating non-linear reading order.

### Extraction & OCR Routing (`NativePdfTextExtractor`)
`localshift.documents.text_extractor.NativePdfTextExtractor.extract()` extracts text page-by-page using an intelligent routing strategy:
- **Digital Text Pages (`TEXT_PRESENT`):** Uses fast native stream extraction via PDFium; preserves exact character stream and spacing without OCR overhead.
- **Scanned Pages (`IMAGE_LIKELY`):** Bounded page rendering at configured DPI (`PdfPageRenderer`), followed by local text detection and recognition (`RapidOcrEngine`).
- **Mixed Pages (`MIXED_OR_UNCERTAIN`):** Performs native extraction, and if sparse text with images is present, runs OCR and merges distinct text without duplication.
- **Blank Pages (`EMPTY_OR_UNKNOWN`):** Emits clean empty text without running OCR, preventing hallucinated characters.
- **Encoding:** Deterministic UTF-8 encoding; preserves accented Latin characters, diacritics, and currency symbols.
- **Resource Constraints:** `MAX_PAGES_LIMIT = 2000`, `MAX_IMAGE_PIXELS = 16_000_000` (16 MP per page), and ISO 32000 dimension limits.
- **Cooperative Cancellation:** Polled before processing each page and prior to raster OCR execution.
- **Empty-Document Handling:** If a document contains zero text characters across all pages, `to_plain_text()` returns `""` (no artificial page separator headers are emitted).

---

## 4. Route Options

| Route | Option Name | Type | Default | Description |
|---|---|---|---|---|
| `*` → `jpeg` | `jpeg_background` | `RGB tuple` | `(255, 255, 255)` | Background fill color used when compositing transparent RGBA images into JPEG. |
| `pdf` → `txt` | `page_separator` | `str` | `"\n\n--- Page {page} ---\n\n"` | Formatting template string inserted between consecutive extracted pages. |
| `pdf` → `txt` | `ocr_mode` | `str` | `"auto"` | OCR routing strategy: `"auto"` (OCR scans and sparse pages), `"native_only"` (bypass OCR), `"force_ocr"` (rasterize all pages). |
| `pdf` → `txt` | `ocr_dpi` | `int` | `200` | Resolution in DPI for raster page rendering prior to OCR (72–400, default 200). |
| `pdf` → `txt` | `ocr_language` | `str` | `"auto"` | Target OCR language: `'auto'`/`'en'`/`'ch'` (bundled) or registered language pack (e.g. `'hi'`). |
| `pdf` → `docx` | `ocr_mode` | `str` | `"auto"` | OCR routing strategy: `"auto"` (OCR scans and sparse pages), `"native_only"` (bypass OCR), `"force_ocr"` (rasterize all pages). |
| `pdf` → `docx` | `ocr_dpi` | `int` | `200` | Resolution in DPI for raster page rendering prior to OCR (72–400, default 200). |
| `pdf` → `docx` | `ocr_language` | `str` | `"auto"` | Target OCR language: `'auto'`/`'en'`/`'ch'` (bundled) or registered language pack (e.g. `'hi'`). |
| `pdf` → `docx` | `extract_images` | `bool` | `True` | Extract and embed graphics and illustrations from digital pages into the Word document. |
| `docx` → `pdf` | `renderer` | `str` | `"auto"` | Offline rendering engine: `'auto'` (detect LibreOffice or Word), `'libreoffice'`, or `'word_com'`. |
| `docx` → `pdf` | `timeout` | `int` | `60` | Maximum rendering duration in seconds (5–300, default 60). |
| `pdf` → `png` | `dpi` | `int` | `150` | Rendering resolution in DPI (72–400, default 150). |
| `pdf` → `png` | `pages` | `str` / `int` / `list` | `"all"` | Page selection specification: `"all"`, single page (e.g. `1`), range (`"1-3"`), or comma list (`"1, 3, 5"`). |
| `pdf` → `png` | `output_pattern` | `str` | `"{stem}_page_{page}.{ext}"` | Output filename pattern supporting `{stem}`, `{page}`, `{page_count}`, `{ext}` (or formatting like `{page:02d}`). |
| `pdf` → `jpeg` | `dpi` | `int` | `150` | Rendering resolution in DPI (72–400, default 150). |
| `pdf` → `jpeg` | `pages` | `str` / `int` / `list` | `"all"` | Page selection specification: `"all"`, single page, ranges, or lists. |
| `pdf` → `jpeg` | `output_pattern` | `str` | `"{stem}_page_{page}.{ext}"` | Output filename pattern with token substitutions. |
| `pdf` → `jpeg` | `quality` | `int` | `85` | JPEG compression quality level (1–100, default 85). |
| `pdf` → `jpeg` | `jpeg_background` | `RGB tuple` | `(255, 255, 255)` | Background fill color used when compositing transparent areas to JPEG. |
| `* (image)` → `pdf` | `page_size` | `str` | `"original"` | Target PDF page dimensions: `"original"` / `"fit_to_image"`, `"a4"`, or `"letter"`. |
| `* (image)` → `pdf` | `fit` | `str` | `"contain"` | Scaling geometry when `page_size` is fixed: `"contain"` (aspect-fit within margins) or `"cover"` (aspect-fill with centered crop). |
| `* (image)` → `pdf` | `orientation` | `str` | `"auto"` | Page orientation when `page_size` is fixed: `"auto"` (matches image aspect ratio), `"portrait"`, or `"landscape"`. |
| `* (image)` → `pdf` | `margin` | `float` / `int` | `0.0` | Margin in points (1/72 inch) applied around the image area (0.0 to < half page dimension). |
| `* (image)` → `pdf` | `background_color` | `RGB tuple` | `(255, 255, 255)` | RGB background fill color for transparent image areas and page margins. |
| `* (image)` → `pdf` | `dpi` | `int` | `150` | PDF rendering resolution in DPI (72–400, default 150). Determines pixel density for points conversion. |
| `* (image)` → `pdf` | `quality` | `int` | `85` | Output image quality level (1–100, default 85) for compression. |
| `* (image)` → `pdf` | `additional_sources` | `list[str/Path]` | `[]` | Ordered list of additional image source paths to assemble into a single multipage PDF. |
| `* (image)` → `pdf` | `output_name` | `str` | `None` | Custom output filename (stem or stem+ext) used when assembling multiple images into a single PDF. |

---

## 5. Offline OCR Engine Details

- **Engine:** RapidOCR (v1.2.3) powered by ONNX Runtime CPU (v1.26.0).
- **Models:** Bundled PP-OCRv4 detection (`ch_PP-OCRv4_det_infer.onnx`), recognition (`ch_PP-OCRv4_rec_infer.onnx`), and orientation classifier (`ch_ppocr_mobile_v2.0_cls_infer.onnx`).
- **Licensing:** Apache-2.0 for package and model weights.
- **Offline Guarantee:** 100% local CPU execution. Zero telemetry, zero cloud calls, zero runtime model downloads.
- **Orientation Recovery:**
  - 180° upside-down scan recovery: Automatically detects inverted text chips and inverts the whole-page raster so that detection boxes and reading order remain natural top-to-bottom.
  - 90°/270° sideways scan recovery: Automatically detects vertical line boxes and rotates the image to upright orientation.
- **Language Coverage:**
  - Supported: English, Latin-script alphabets, Chinese.
  - Unsupported (in default bundle): Non-Latin scripts such as Devanagari (Hindi), Arabic, Cyrillic. Scanned pages in these languages detect Latin portions but require separate specialized language weights for native script characters.

---

## 6. DOCX → PDF Rendering Engine Details & Limitations

### Architecture & Discovery:
- **Renderer:** `localshift.documents.docx_renderer.DocxToPdfRenderer` provides offline rendering without third-party cloud services or automatic network downloads.
- **Backends:**
  1. **LibreOffice Headless:** Discovered via `LOCALSHIFT_LIBREOFFICE_PATH`, `PATH`, or standard install locations (`Program Files/LibreOffice/program/soffice.exe`). Executed with isolated user profiles (`-env:UserInstallation`) to ensure thread-safety and eliminate profile lock contention.
  2. **Microsoft Word COM Automation:** On Windows, utilizes `Word.Application` via PowerShell with non-interactive execution and alert suppression (`$w.DisplayAlerts = 0`).
- **Dynamic Route Advertising:** If neither LibreOffice nor Microsoft Word is detected, `AdapterRegistry` omits `("docx", "pdf")` from `supported_routes()`, and planning emits an actionable `FindingCode.ADAPTER_UNAVAILABLE` finding.
- **Sandboxing & Immutability:** Input documents are never modified. Execution occurs against temporary copies in isolated directories, and all artifacts are pruned in `finally` blocks.

### Rendering Limitations:
1. **External Office Suite Dependency:** High-fidelity DOCX rendering relies on either LibreOffice or Microsoft Word being installed on the user's host machine. Pure Python layout rendering of DOCX without an office suite is mathematically imperfect and not supported.
2. **Interactive Elements & Macros:** Word macros and VBA scripts are blocked/disabled during conversion.
3. **External Linked Resources:** Remote images or external OLE links are not fetched from the internet (strict offline guarantee); they will render as blank boxes or static fallback representations.
4. **Font Substitution:** If a DOCX specifies fonts not present in the local OS font directory, the host rendering engine substitutes standard fallback fonts (e.g., Arial / Calibri / Times New Roman).
5. **Dynamic Fields:** Date, page number, and table of contents fields are evaluated statically at render time.

## 7. PDF → PNG/JPEG Raster Export Engine Details

### Architecture & Capabilities
- **Engine:** `localshift.documents.pdf_image_exporter.PdfToImageExporter` provides fully offline, resource-bounded rasterization of PDF pages to high-quality PNG or JPEG images using Google PDFium (`PdfPageRenderer`) and Pillow.
- **Multipage Batch Export:** Single or multipage PDFs can be exported. Every selected page is rasterized independently and placed as a separate, correctly numbered image file in the target directory.
- **Single-Page Optimization:** Single-page documents default to `{stem}.{ext}` unless a custom pattern is specified, avoiding unnecessary `_page_1` suffixes on one-page files.
- **Page Selection:** Flexible `pages` option supporting:
  - `"all"` or `""`: Export all pages.
  - Single page: Integer (e.g. `2`) or string (`"2"`).
  - Page ranges: `"1-5"`, `"2-2"`.
  - Comma-delimited lists: `"1, 3, 5"`.
  - Mixed ranges and lists: `"1-3, 5"`.
  - Strict validation: Out-of-bounds page numbers, zero/negative pages, and inverted ranges (e.g. `"5-2"`) are rejected early with `InvalidInputError`.
- **Configurable Rendering:**
  - **DPI:** 72–400 (default 150). Clamped to safe memory ceilings to prevent OOM errors on oversized documents.
  - **JPEG Quality:** 1–100 (default 85) with customizable RGB background fill when compositing transparent vector/image content.
  - **Output Pattern:** User-configurable template string supporting tokens `{stem}`, `{page}`, `{page_count}`, and `{ext}` (e.g. `"{stem}_p{page:02d}.{ext}"`). Traversal tokens (`/`, `\`, `..`) are strictly forbidden. When exporting multiple pages, patterns lacking `{page}` are rejected to prevent file clobbering.
- **Collision Protection & Atomicity:**
  - In-process reservations (`reserve_output_path`) ensure concurrency safety.
  - Each page is rendered to a temporary file on the destination volume and atomically moved (`os.replace`) to its final path.
  - Pre-existing files in the output directory are protected with Windows-style collision suffixes (e.g. `_page_1 (2).png`).
  - Cooperative cancellation is checked between pages. On failure or cancellation, all partially rendered temporary and output files are cleanly removed.
- **Multi-Output Results:**
  - `ConversionResult.output_path` points to the primary output (first exported page) for backwards compatibility.
  - `ConversionResult.output_paths` contains the complete ordered tuple of all exported page image paths.
  - `ConversionResult.output_bytes` reports the aggregate total size across all exported image files.

---

## 8. Image → PDF Conversion Engine Details & Assembly

- **Supported Source Formats:** PNG, JPEG (`.jpg`, `.jpeg`), WebP, BMP, and TIFF (`.tif`, `.tiff`).
- **Engine:** Built upon Pillow's raster image decoding and compliant PDF generation backend.
- **Conversion Modes:**
  - **Single Image → PDF:** Converts a single raster image into a 1-page PDF. Default output naming matches `{stem}.pdf`.
  - **Multiple Images → Ordered Multipage PDF:** Assembles multiple raster images in explicit sequence into a single multipage PDF document using Pillow's `save_all=True, append_images=...`. Destination naming defaults to `{first_stem}.pdf` or user-specified `output_name`.
  - **Batch Conversion:** Converts multiple distinct images into individual 1-page PDF documents via `convert_images_batch_to_pdf()`.
- **Layout & Dimension Handling:**
  - **Page Sizes:** `"original"` / `"fit_to_image"` matches exact image aspect ratio and dimensions at specified DPI ($W_{\text{pt}} = W_{\text{px}} \times 72 / \text{DPI}$); `"a4"` ($595.28 \times 841.89\text{ pt}$); `"letter"` ($612.0 \times 792.0\text{ pt}$).
  - **Fit Modes:** `"contain"` scales the image proportionally to fit within printable page area (page bounds minus margins); `"cover"` scales proportionally to fill the page area completely and crops symmetrically from center.
  - **Orientation:** `"auto"` automatically selects portrait or landscape to match the input image's aspect ratio. Explicit `"portrait"` or `"landscape"` forces page orientation.
  - **Margins:** Point-based margins ($\ge 0$, validated to prevent negative printable dimensions). Margins are filled with `background_color`.
  - **Background & Transparency:** RGBA, LA, or paletted transparency is composited over the configurable `background_color` (RGB 3-tuple, default white).
  - **Color Mode Normalization:** Non-RGB modes (CMYK, Grayscale `L`, Bilevel `1`, Paletted `P`) are cleanly and safely normalized to RGB.
  - **EXIF Orientation:** EXIF orientation tags (e.g. mobile photos) are automatically transposed prior to dimension calculation.
- **Resource Limits & Security:**
  - Strict pixel ceiling of 16,000,000 pixels (16 MP) per image prevents decompression bomb denial-of-service.
  - Input file validation ensures files exist, are regular files, and do not exceed 250 MiB.
  - Safe temporary files and atomic placement (`os.replace`) ensure target files are never partially written or left corrupted on failure.

---

## 9. PDF Workbench Subsystem (Merge, Split, Extract, Reorder, Rotate)

The PDF Workbench subsystem (`localshift.documents.pdf_workbench.PdfWorkbench`) provides high-performance, fully offline structural manipulation for PDF documents. Unlike format conversion routes (which transcode between distinct data formats), workbench operations perform lossless in-format PDF transformations.

### Supported Operations:
1. **Merge (`merge_pdfs`):**
   - Combines multiple PDF documents into a single document in the exact specified order.
   - Preserves each page's dimensions, media boxes, annotations, graphics, fonts, and rotation angles.
   - Enforces a combined ceiling of 2000 pages (`MAX_PAGES_LIMIT`).
   - Default output naming: `{first_stem}_merged.pdf` with collision suffixing (` (2)`).
2. **Split (`split_pdf`):**
   - Splits a PDF document into individual single-page PDF files.
   - Supports page subset selections (e.g., `"all"`, `"1-3"`, `"1, 3, 5"`).
   - Configurable filename patterns (e.g. `"{stem}_page_{page}.pdf"`) with mandatory `{page}` token when splitting multiple pages.
3. **Extract (`extract_pdf_pages`):**
   - Extracts a chosen subset of pages into a single new PDF document.
   - Preserves original page sequence or requested page subsets without transcoding or raster re-encoding.
4. **Reorder (`reorder_pdf_pages`):**
   - Rearranges pages using a validated 1-based sequence (e.g., `[3, 1, 2]`).
   - Bounds-checked: validates every index against total document page count.
5. **Rotate (`rotate_pdf_pages`):**
   - Rotates selected pages by 90°, 180°, or 270° (or negative equivalents like -90°).
   - Supports relative rotation (`(current + angle) % 360`) or absolute rotation (`angle % 360`).
   - Non-multiple-of-90 angles (e.g., 45°) are rejected with `InvalidInputError`.

### Safety & Integrity Controls:
- **Zero Input Mutation:** Input source files are strictly read-only; source documents are never written to or modified in place.
- **Preflight Inspection:** Corrupted, password-protected (encrypted), non-PDF, or 0-page files are rejected before output files are reserved.
- **Atomic Placement:** Operations write to volume-local temporary files and atomically replace destination paths (`os.replace`).
- **Cooperative Cancellation:** Polled between documents/pages; on cancellation or failure, all partially generated outputs and reservations are cleanly removed.
- **Permissive Licensing:** Built exclusively on Google PDFium via `pypdfium2` (Apache-2.0 / BSD-3). Zero AGPL or non-commercial dependencies.

---

## 10. Unified PySide6 Desktop GUI Workflows

LocalShift provides a native Windows desktop interface built with PySide6 (LGPL-3.0) organized into 5 dedicated workflow tabs:

### 1. General File Converter (`FileConverterTab`)
- Multi-format batch conversion queue supporting drag-and-drop file additions.
- Dynamic per-file target format dropdown populated via `output_formats_for(path)`.
- Batch options panel for OCR mode (`auto`, `native`, `force`), resolution DPI (72–400), JPEG compression quality (1–100), and page selection.
- Asynchronous batch conversion via `BatchConversionWorker` (`QThread`) with cooperative cancellation and per-item status tracking.

### 2. Document Interchange: PDF ↔ DOCX (`DocxInterchangeTab`)
- Dedicated document interchange workflow with radio direction switching:
  - **PDF → DOCX**: Full document structure extraction and OCR with selectable engine mode.
  - **DOCX → PDF**: High-fidelity offline document rendering with real-time backend discovery badge (Microsoft Word COM or LibreOffice Headless).

### 3. PDF to Images Rasterizer (`PdfRasterizeTab`)
- Rasterizes PDF pages into PNG (lossless) or JPEG (compressed) images.
- Configurable DPI (72–400), JPEG quality (1–100), page selection syntax (`all`, `1-3`, `1, 3, 5`), and custom naming patterns with `{stem}` and `{page:02d}` tokens.

### 4. Images to PDF Multi-Image Assembly (`ImagesToPdfTab`)
- Combines multiple raster images (`png`, `jpeg`, `webp`, `bmp`, `tiff`) into one ordered multipage PDF document.
- Interactive reordering controls: Move Up, Move Down, Remove, Clear.
- Formatting controls: Page size (`original`, `a4`, `letter`), Fit mode (`contain`, `cover`), Orientation (`auto`, `portrait`, `landscape`), point margins (0–144 pt), and custom background colors.

### 5. PDF Workbench (`PdfWorkbenchTab`)
- Page-level PDF manipulation workbench supporting:
  - **Merge**: Multi-PDF ordered assembly with Move Up/Down reordering.
  - **Split**: PDF page bursting with subset page selection and custom naming patterns.
  - **Extract**: Chosen page subsets extracted to a single new PDF document.
  - **Reorder**: Page resequencing via validated 1-based comma-separated integer sequences.
  - **Rotate**: Page rotation by 90°, 180°, or 270° with relative/absolute mode toggle.

---

## 11. Known Gaps and Deferred Capabilities

1. **Multilingual OCR Weights:** Hindi / Devanagari OCR models are not bundled in the default distribution to keep binary footprint lean (~13.7 MB models).
2. **Advanced Typography & Vector Graphics:** Vector paths (PDF line art) are not converted to Word shapes; raster illustrations are extracted and embedded as PNG images.
3. **Rotated Native Pages:** Pages with `/Rotate 90` or `/Rotate 270` dictionary tags are extracted by PyPDFium2 in native character stream order; OCR raster mode detects and rights orientation automatically, but native extraction preserves raw stream order.
4. **Complex Vector-Drawn Form Grids:** Forms with key-value grid cells drawn exclusively using PDF vector paths (without character-level tabular delimiters) require heuristic visual layout parsing to avoid column merging.

---

## 12. Conversion Quality Gate Release Criteria

To ensure release quality without masking defects behind aggregate averages, every production release candidate must satisfy measurable, category-specific thresholds:

| Document Category | Target Metric | Release Threshold | Actual Holdout Result | Gate Status |
|---|---|---|---|---|
| **Born-Digital Text & Specifications** | CER / WER (Native & DOCX) | $\text{CER} \le 0.5\%$, $\text{WER} \le 1.0\%$ | $\text{CER} = 0.0\%$, $\text{WER} = 0.0\%$ | **PASSED** |
| **Financial Tables & Schedules** | Table cell accuracy & CER | $\text{CER} \le 5.0\%$, 100% table recovery | $\text{CER} = 3.5\%$, 2/2 tables recovered | **PASSED** |
| **Scanned Documents (Upright & Inverted)** | CER in OCR Mode | $\text{CER} \le 8.0\%$ | $\text{CER} = 4.4\%$ | **PASSED** |
| **Mixed Documents (Digital + Scans)** | Degraded scan CER | $\text{CER} \le 5.0\%$ | $\text{CER} = 1.9\%$ | **PASSED** |
| **Multilingual Latin / Accented Documents** | Unicode preservation | 100% glyph match | 100% glyph match | **PASSED** |
| **Multi-page Enterprise Bylaws (10+ pages)** | Latency & Peak Memory | $\text{Time} < 500\text{ ms}$, $\text{Mem} < 5\text{ MB}$ | $200.1\text{ ms}$, $2.4\text{ MB}$ | **PASSED** |
| **Corrupted / Damaged Streams** | Safety & Error Trapping | 0 unhandled crashes | Trapped `InvalidInputError` | **PASSED** |
| **Visual QA (Word COM Headless Render)** | Page count parity & render | 100% pass across readable fixtures | 100% pass (9/9 readable) | **PASSED** |
