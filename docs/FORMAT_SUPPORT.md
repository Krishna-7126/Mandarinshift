# LocalShift — Format Support Specification

**Version:** 0.6.0 (Updated: Milestone LS-BE-006D)  
**Status:** Implemented & Verified  

---

## 1. Supported Format Matrix

LocalShift conversion capabilities are explicit and directional. A format pair is available only if an adapter is registered for that route in the `AdapterRegistry`.

### Canonical Formats

| Format Key | Category | Extensions | Default Sniffing | Role in LocalShift |
|---|---|---|---|---|
| `png` | Raster Image | `.png` | Magic bytes (`\x89PNG\r\n\x1a\n`) | Input & Output |
| `jpeg` | Raster Image | `.jpeg`, `.jpg` | Magic bytes (`\xff\xd8\xff`) | Input & Output |
| `webp` | Raster Image | `.webp` | Magic bytes (`RIFF....WEBP`) | Input & Output |
| `bmp` | Raster Image | `.bmp` | Magic bytes (`BM`) | Input & Output |
| `tiff` | Raster Image | `.tiff`, `.tif` | Magic bytes (`II*\x00` / `MM\x00*`) | Input & Output |
| `pdf` | Document | `.pdf` | Magic bytes (`%PDF-`) | **Input Only** |
| `txt` | Plain Text | `.txt` | Plain text / UTF-8 | **Output Only** |

---

## 2. Directional Conversion Routes (21 Total)

### Image-to-Image Routes (20 Routes via `PillowImageAdapter`)
Every distinct pair among `{"png", "jpeg", "webp", "bmp", "tiff"}` is supported in both directions:
- `png` ⇄ `jpeg`, `png` ⇄ `webp`, `png` ⇄ `bmp`, `png` ⇄ `tiff`
- `jpeg` ⇄ `webp`, `jpeg` ⇄ `bmp`, `jpeg` ⇄ `tiff`
- `webp` ⇄ `bmp`, `webp` ⇄ `tiff`
- `bmp` ⇄ `tiff`

*Same-format conversion (e.g. `png` → `png`) is intentionally rejected as a no-op.*

### Document Routes (1 Route via `PdfDocumentAdapter`)
- `pdf` → `txt`: Hybrid native text extraction and offline OCR to UTF-8 plain text.

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

---

## 5. Offline OCR Engine Details

- **Engine:** RapidOCR (v1.2.3) powered by ONNX Runtime CPU (v1.26.0).
- **Models:** Bundled PP-OCRv4 detection (`ch_PP-OCRv4_det_infer.onnx`), recognition (`ch_PP-OCRv4_rec_infer.onnx`), and orientation classifier (`ch_ppocr_mobile_v2.0_cls_infer.onnx`).
- **Licensing:** Apache-2.0 for package and model weights.
- **Offline Guarantee:** 100% local CPU execution. Zero telemetry, zero cloud calls, zero runtime model downloads.
- **Language Coverage:**
  - Supported: English, Latin-script alphabets, Chinese.
  - Unsupported (in default bundle): Non-Latin scripts such as Devanagari (Hindi), Arabic, Cyrillic. Scanned pages in these languages detect Latin portions but require separate specialized language weights for native script characters.

---

## 6. Known Gaps and Deferred Capabilities

1. **Multilingual OCR Weights:** Hindi / Devanagari OCR models are not bundled in the default distribution to keep binary footprint lean (~13.7 MB models).
2. **Document Reconstruction (PDF → DOCX):** Structured layout reconstruction into editable Word documents is deferred to milestone **LS-BE-006E**.
3. **PDF Generation (DOCX/Image → PDF):** LocalShift does not currently generate PDF files.
